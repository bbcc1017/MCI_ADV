"""라우팅 방향·단위·폴백과 기존 지도 JSON 호환성을 검증한다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src" / "sce_src"), str(ROOT / "src" / "vis_src")]
from make_csv_yaml_dynamic import ScenarioGenerator
from _map_controls import create_map
from _route_geometry import osrm_payload, index_hospital_routes, prefetch_osrm_geometry


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gen = ScenarioGenerator.__new__(ScenarioGenerator)
        self.gen.road_provider = "osrm"
        self.gen.osrm_url = "https://example.test"
        self.gen.api_call_count = 0
        self.gen.get_road_distance = Mock(return_value=(9.0, 8.0))
        self.kwargs = dict(save_json_dir=str(Path(self.temp.name) / "routes" / "center2site"),
                           route_type="center2site", names=["A", "B"], start_label="center", goal_label="site")
        self.starts = [(37.1, 127.1), (37.2, 127.2)]
        self.ends = [(37.3, 127.3)] * 2
        self.sleep = patch("make_csv_yaml_dynamic.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def response(self, distances, durations):
        response = Mock(status_code=200)
        response.json.return_value = {"code": "Ok", "distances": distances, "durations": durations}
        return response

    @patch("make_csv_yaml_dynamic._HTTP.get")
    def test_many_to_one_direction_units_and_raw_response(self, get):
        get.return_value = self.response([[1200], [3400]], [[90], [180]])
        actual = self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs)
        self.assertEqual(actual, [(1.2, 1.5), (3.4, 3.0)])
        self.gen.get_road_distance.assert_not_called()
        self.assertEqual(get.call_args.kwargs["params"]["sources"], "0;1")
        self.assertEqual(get.call_args.kwargs["params"]["destinations"], "2")
        self.assertIn("127.1,37.1;127.2,37.2;127.3,37.3", get.call_args.args[0])
        record = json.loads((Path(self.kwargs["save_json_dir"]) / "001_B.json").read_text(encoding="utf-8"))
        self.assertEqual(record["meta"]["center"], [127.2, 37.2])
        self.assertEqual(record["meta"]["site"], [127.3, 37.3])
        pointer = record["payload"]["osrm_table"]
        raw = json.loads((Path(self.kwargs["save_json_dir"]) / pointer["response_file"]).read_text(encoding="utf-8"))
        self.assertEqual(raw, get.return_value.json.return_value)
        self.assertEqual(pointer["row"], 1)

    @patch("make_csv_yaml_dynamic._HTTP.get")
    def test_one_to_many_preserves_hospital_direction(self, get):
        get.return_value = self.response([[1200, 3400]], [[90, 180]])
        self.kwargs.update(route_type="hos2site", start_label="site", goal_label="hospital")
        actual = self.gen.get_road_distance_batch(self.ends, self.starts, **self.kwargs)
        self.assertEqual(actual, [(1.2, 1.5), (3.4, 3.0)])
        self.assertEqual(get.call_args.kwargs["params"]["sources"], "0")
        self.assertEqual(get.call_args.kwargs["params"]["destinations"], "1;2")

    @patch("make_csv_yaml_dynamic._HTTP.get")
    def test_unreachable_cell_only_uses_route_and_keeps_real_zero(self, get):
        get.return_value = self.response([[0], [None]], [[0], [None]])
        self.assertEqual(self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs), [(0, 0), (9, 8)])
        self.gen.get_road_distance.assert_called_once()
        self.assertEqual(self.gen.get_road_distance.call_args.args, (self.starts[1], self.ends[1]))

    @patch("make_csv_yaml_dynamic._HTTP.get")
    def test_invalid_table_falls_back_without_fabricating_distances(self, get):
        for response in [self.response([[1]], [[2]]), self.response([[float("nan")], [1]], [[1], [1]]),
                         self.response([["invalid"], [1]], [[1], [1]])]:
            get.return_value = response
            self.assertEqual(self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs), [(9, 8)] * 2)
        get.side_effect = requests.Timeout("test timeout")
        self.assertEqual(self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs), [(9, 8)] * 2)

    @patch("make_csv_yaml_dynamic._HTTP.get")
    def test_rate_limit_retries_then_succeeds(self, get):
        get.side_effect = [Mock(status_code=429), self.response([[1000], [2000]], [[60], [120]])]
        self.assertEqual(self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs), [(1, 1), (2, 2)])
        self.assertEqual(get.call_count, 2)

    def test_chunk_limit(self):
        starts = [(37 + i / 1000, 127) for i in range(85)]
        ends = [(36, 128)] * 85
        self.kwargs["names"] = [str(i) for i in range(85)]
        def table(coords, sources, destinations):
            self.assertLessEqual(len(coords), 80)
            return {"distances": [[1000]] * len(sources), "durations": [[60]] * len(sources)}
        self.gen._osrm_table = Mock(side_effect=table)
        self.assertEqual(self.gen.get_road_distance_batch(starts, ends, **self.kwargs), [(1, 1)] * 85)
        self.assertEqual(self.gen._osrm_table.call_count, 3)

    def test_kakao_still_calls_original_dispatcher_in_order(self):
        self.gen.road_provider = "kakao"
        self.gen._osrm_table = Mock(side_effect=AssertionError("Kakao must not use table"))
        self.gen.get_road_distance_batch(self.starts, self.ends, **self.kwargs)
        self.gen._osrm_table.assert_not_called()
        calls = self.gen.get_road_distance.call_args_list
        self.assertEqual([call.args for call in calls], list(zip(self.starts, self.ends)))
        self.assertEqual([call.kwargs["source_index"] for call in calls], [0, 1])


class MapTests(unittest.TestCase):
    @patch("_route_geometry.st.warning")
    @patch("_route_geometry._fetch_geometry", side_effect=requests.Timeout("offline"))
    def test_geometry_failure_is_visible_and_is_not_retried_in_same_render(self, fetch, warning):
        route = {"meta": {"service": "table", "osrm_url": "https://example.test", "start_label": "site",
                          "goal_label": "hospital", "site": [127, 37], "hospital": [128, 38]}, "payload": {}}
        prefetch_osrm_geometry([route])
        self.assertTrue(route["_geometry_failed"])
        self.assertEqual(osrm_payload(route), {})
        fetch.assert_called_once()
        warning.assert_called_once()

    @patch("_route_geometry._fetch_geometry")
    def test_prefetch_skips_existing_geometry_and_keeps_table_provenance(self, fetch):
        fetch.return_value = {"routes": [{"geometry": {"coordinates": [[127, 37], [128, 38]]}}]}
        route = {"meta": {"service": "table", "osrm_url": "https://example.test", "start_label": "site",
                          "goal_label": "hospital", "site": [127, 37], "hospital": [128, 38]},
                 "payload": {"osrm_table": {"row": 0, "column": 1}}}
        old = {"meta": {"service": "table"}, "payload": {"osrm_response": {"routes": []}}}
        prefetch_osrm_geometry([route, old])
        fetch.assert_called_once_with("https://example.test", (127, 37), (128, 38))
        self.assertIn("osrm_table", route["payload"])
        self.assertEqual(route["payload"]["osrm_response"], fetch.return_value)

    def test_hospital_routes_follow_simulation_order_and_duplicate_coordinates(self):
        routes = [{"meta": {"name": "A", "source_index": 0, "hospital": [127, 37]}},
                  {"meta": {"name": "B", "source_index": 1, "hospital": [128, 38]}},
                  {"meta": {"name": "A", "source_index": 2, "hospital": [129, 39]}}]
        hospitals = [{"Index": 0, "Hospital Name": "B"},
                     {"Index": 1, "Hospital Name": "A", "x좌표": 129, "y좌표": 39},
                     {"Index": 2, "Hospital Name": "A", "x좌표": 127, "y좌표": 37}]
        mapped = index_hospital_routes(hospitals, routes)
        self.assertEqual([mapped[i] for i in range(3)], [routes[1], routes[2], routes[0]])

    @patch("_route_geometry._fetch_geometry")
    def test_old_route_json_needs_no_network(self, fetch):
        original = {"routes": [{"geometry": {"coordinates": [[127, 37], [128, 38]]}}]}
        self.assertIs(osrm_payload({"payload": {"osrm_response": original}}), original)
        fetch.assert_not_called()

    @patch("_route_geometry._fetch_geometry")
    def test_table_geometry_is_deferred_and_reused(self, fetch):
        fetch.return_value = {"routes": [{"geometry": {"coordinates": [[127, 37], [128, 38]]}}]}
        record = {"meta": {"service": "table", "osrm_url": "https://example.test",
                           "start_label": "site", "goal_label": "hospital", "site": [127, 37], "hospital": [128, 38]},
                  "payload": {"osrm_table": {"row": 0, "column": 1}}}
        self.assertEqual(osrm_payload(record), fetch.return_value)
        self.assertEqual(osrm_payload(record), fetch.return_value)
        fetch.assert_called_once_with("https://example.test", (127, 37), (128, 38))
        self.assertIn("osrm_table", record["payload"])

    def test_map_controls_render_for_both_map_modes(self):
        html = create_map([37, 127]).get_root().render()
        for marker in ["도로지도", "회색지도", "위성지도 전환", "zoomControl.getContainer()", '"preferCanvas": true']:
            self.assertIn(marker, html)
        self.assertNotIn("st_folium", html)


if __name__ == "__main__":
    unittest.main()
