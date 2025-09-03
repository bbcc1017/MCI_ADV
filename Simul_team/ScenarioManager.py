import math
import pandas as pd
import numpy as np
import json

from EntityManager import EntityManager
from EventManager import EventManager
class ScenarioManager():
    def __init__(self, configs, rng=None):
        if rng is not None:
            self.rng = rng
        else:
            self.rng = np.random.default_rng()
        self.scenario = {}
        # 1. 개체 정보 생성
        self.en_manager = EntityManager(configs['entity_info'].keys())
        for en_name, raw_prop in configs['entity_info'].items():
            if en_name == "patient":
                reg_prop = self.setup_patient(raw_prop)
            elif en_name == "hospital":
                reg_prop = self.setup_hospital(raw_prop)
            elif en_name == "ambulance":
                reg_prop = self.setup_ambulance(raw_prop)
            elif en_name == "uav":
                reg_prop = self.setup_uav(raw_prop)
            else:
                raise NotImplementedError(f"{en_name}은 아직 구현되지 않은 개체입니다.")
            self.en_manager.en_register(en_name, reg_prop)
        self.scenario['EntityManager'] = self.en_manager

        # 2. Event 정보 생성
        with open(configs['event_info_path'], "r") as f:
            ev_info = json.load(f)
        self.ev_manager = EventManager(ev_info, self.en_manager, rng=self.rng)
        self.scenario['EventManager'] = self.ev_manager

    def set_seed(self, rng):
        self.rng = rng
        self.ev_manager.set_seed(rng)
    def setup_patient(self, cfg_patient):
        reg_prop ={}
        reg_prop['incident_size'] = cfg_patient['incident_size']
        incident_loc = (cfg_patient['latitude'], cfg_patient['longitude'])
        incident_type = cfg_patient['incident_type']
        try:
            patient_info = pd.read_csv(cfg_patient['info_path'])
            if incident_type is not None:
                raise NotImplementedError("사고 type 정보 반영은 아직 구현 전입니다.")
            assert math.isclose(patient_info['ratio'].sum(), 1.0), "환자 비율 합은 1이어야 합니다."
            reg_prop['patient_info'] = patient_info
            # p_info_dict = patient_info.set_index("type").to_dict(orient="index")
            # reg_prop.update({'Red': p_info_dict['Red'],
            #                  'Yellow': p_info_dict['Yellow'],
            #                  'Green': p_info_dict['Green'],
            #                  'Black': p_info_dict['Black']})
        except FileNotFoundError:
            print("환자 데이터가 주어지지 않았습니다.")
        return reg_prop

    def get_lognormal_param(self, m):
        v = np.power(m * 0.4, 2)
        mean_logn = np.zeros_like(m, dtype=float)
        mask = m > 0 # element 값이 0인 경우 0으로 남기기
        mean_logn[mask] = np.log(m[mask] / np.sqrt(1 + v[mask] / np.power(m[mask], 2)))
        std_logn = np.zeros_like(m, dtype=float)
        std_logn[mask] = np.sqrt(np.log(1 + v[mask] / np.power(m[mask], 2)))
        # mean_logn = np.log(m / np.sqrt(1 + v / np.power(m, 2)))
        # std_logn = np.sqrt(np.log(1 + v / np.power(m, 2)))
        return mean_logn, std_logn # mean, std of underlying normal distribution

    def setup_hospital(self, cfg_hospital):
        reg_prop ={} # hos_num, hos_max_capa, hos_tier, d_HtoH_euc, d_HtoH_road, d_HtoS_euc, d_HtoS_road
        # From data
        if cfg_hospital['load_data']:
            try:
                # 병원 capa, 등급 정보
                hos_info = pd.read_csv(cfg_hospital['info_path'])
                reg_prop['hos_num'] = len(hos_info)
                # reg_prop['hos_max_capa'] = hos_info['병상수'].to_numpy(dtype='int32')
                # reg_prop['hos_max_queue'] = hos_info['queue_capa'].to_numpy(dtype='int32')
                # ========== [수정] 병상수 -> 수술실수, queue_capa -> 병상수 ==========
                reg_prop['hos_max_capa'] = hos_info['수술실수'].to_numpy(dtype='int32')
                reg_prop['hos_max_queue'] = hos_info['병상수'].to_numpy(dtype='int32')
                reg_prop['hos_tier'] = hos_info['종별코드'].to_numpy(dtype='int32')
                reg_prop['hos_max_send'] = cfg_hospital['max_send_coeff'][0]*reg_prop['hos_max_capa'] \
                                           + cfg_hospital['max_send_coeff'][1]*reg_prop['hos_max_queue']
                # 거리 정보
                d_HtoH_euc = pd.read_csv(cfg_hospital['dist_Hos2Hos_euc_info']).iloc[:, 1:]
                reg_prop['d_HtoH_euc'] = d_HtoH_euc.to_numpy(dtype='float32')
                d_HtoH_road = pd.read_csv(cfg_hospital['dist_Hos2Hos_road_info']).iloc[:, 1:]
                reg_prop['d_HtoH_road'] = d_HtoH_road.to_numpy(dtype='float32')
                d_HtoS_euc = pd.read_csv(cfg_hospital['dist_Hos2Site_euc_info']).iloc[:, 1:]
                reg_prop['d_HtoS_euc'] = d_HtoS_euc.to_numpy(dtype='float32')[:,0]
                d_HtoS_road = pd.read_csv(cfg_hospital['dist_Hos2Site_road_info']).iloc[:, 1:]
                reg_prop['d_HtoS_road'] = d_HtoS_road.to_numpy(dtype='float32')[:,0]
            except FileNotFoundError:
                print("병원 데이터 생성에 필요한 파일이 부족합니다.")
        else:
            # call generator
            raise NotImplementedError("시나리오 생성 모듈 불러오기 기능 추가 전입니다.")
        # Modify & Add
        reg_prop['hos_tier'] = np.where(reg_prop['hos_tier']==1, 1, 2) # 1 = 상급종합, 2 = 나머지
        reg_prop['hos_tier1_idx'] = hos_info.index[hos_info['종별코드'] == 1].to_numpy()
        reg_prop['hos_tier2_idx'] = hos_info.index[hos_info['종별코드'] != 1].to_numpy()
        reg_prop['hos_closest_second'] = reg_prop['hos_tier2_idx'][
            np.argmin(reg_prop['d_HtoS_road'][reg_prop['hos_tier2_idx']])] if len(reg_prop['hos_tier2_idx']) else None
        reg_prop['hos_closest_first'] = reg_prop['hos_tier1_idx'][
            np.argmin(reg_prop['d_HtoS_road'][reg_prop['hos_tier1_idx']])] if len(reg_prop['hos_tier1_idx']) else None

        HtoH_road = reg_prop['d_HtoH_road'].copy()
        np.fill_diagonal(HtoH_road, np.inf)
        reg_prop['hos_closest_first_fromH'] = reg_prop['hos_tier1_idx'][np.argmin(HtoH_road[:,reg_prop['hos_tier1_idx']], axis=1)]
        reg_prop['hos_closest_second_fromH'] = reg_prop['hos_tier2_idx'][np.argmin(HtoH_road[:, reg_prop['hos_tier2_idx']], axis=1)]

        return reg_prop

    def setup_ambulance(self, cfg_amb):
        reg_prop ={} # amb_num, amb_dispatch_d, amb_v, amb_handover_time, amb_e_types
        # From data
        if cfg_amb['load_data']:
            try:
                amb_info = pd.read_csv(cfg_amb['dispatch_distance_info'])
                reg_prop['amb_num'] = len(amb_info)
                reg_prop['amb_dispatch_d'] = amb_info['init_distance'].to_numpy(dtype='float32')
                reg_prop['amb_v'] = cfg_amb['velocity']
                reg_prop['amb_handover_time'] = cfg_amb['handover_time']
            except FileNotFoundError:
                print("구급차 데이터 생성에 필요한 파일이 부족합니다.")
        else:
            # call generator
            raise NotImplementedError("시나리오 생성 모듈 불러오기 기능 추가 전입니다.")
        # Modify & Add
        # 1. 초기 출동 시간 parameter 저장
        response_mean = reg_prop['amb_dispatch_d'] * 60 / reg_prop['amb_v'] # unit: minutes
        response_mean_logn, response_std_logn = self.get_lognormal_param(response_mean)
        reg_prop['amb_response_t'] = (response_mean, response_mean_logn, response_std_logn)
        # 2. 병원-현장 이동 시간 parameter 저장
        transport_HtoS_mean = self.en_manager.en_properties['hospital']['d_HtoS_road'] * 60 / reg_prop['amb_v'] # unit: minutes
        transport_HtoS_mean_logn, transport_HtoS_std_logn = self.get_lognormal_param(transport_HtoS_mean)
        reg_prop['amb_HtoS_t'] = (transport_HtoS_mean, transport_HtoS_mean_logn, transport_HtoS_std_logn)
        # 3. 병원-병원 이동 시간 parameter 저장
        transport_HtoH_mean = self.en_manager.en_properties['hospital']['d_HtoH_road'] * 60 / reg_prop['amb_v'] # unit: minutes
        transport_HtoH_mean_logn, transport_HtoH_std_logn = self.get_lognormal_param(transport_HtoH_mean)
        reg_prop['amb_HtoH_t'] = (transport_HtoH_mean, transport_HtoH_mean_logn, transport_HtoH_std_logn)
        # 4.병원 사이 이동 거리 중 최대값 저장
        reg_prop['amb_maxD_HtoH'] = np.max(transport_HtoH_mean_logn, None, None)
        return reg_prop

    def setup_uav(self, cfg_uav):
        reg_prop ={} # uav_num, uav_dispatch_d, uav_v, uav_handover_time, uav_e_types
        # From data
        if cfg_uav['load_data']:
            try:
                uav_info = pd.read_csv(cfg_uav['dispatch_distance_info'])
                reg_prop['uav_num'] = len(uav_info)
                reg_prop['uav_dispatch_d'] = uav_info['init_distance'].to_numpy(dtype='float32')
                reg_prop['uav_v'] = cfg_uav['velocity']
                reg_prop['uav_handover_time'] = cfg_uav['handover_time']
            except FileNotFoundError:
                print("UAV 데이터 생성에 필요한 파일이 부족합니다.")
        else:
            # call generator
            raise NotImplementedError("시나리오 생성 모듈 불러오기 기능 추가 전입니다.")
        # Modify & Add
        # 1. 초기 출동 시간 parameter 저장
        response_mean = reg_prop['uav_dispatch_d'] * 60 / reg_prop['uav_v'] # unit: minutes
        response_mean_logn, response_std_logn = self.get_lognormal_param(response_mean)
        reg_prop['uav_response_t'] = (response_mean, response_mean_logn, response_std_logn)
        # 2. 병원-현장 이동 시간 parameter 저장
        transport_HtoS_mean = self.en_manager.en_properties['hospital']['d_HtoS_euc'] * 60 / reg_prop['uav_v'] # unit: minutes
        transport_HtoS_mean_logn, transport_HtoS_std_logn = self.get_lognormal_param(transport_HtoS_mean)
        reg_prop['uav_HtoS_t'] = (transport_HtoS_mean, transport_HtoS_mean_logn, transport_HtoS_std_logn)
        # 3. 병원-병원 이동 시간 parameter 저장
        transport_HtoH_mean = self.en_manager.en_properties['hospital']['d_HtoH_euc'] * 60 / reg_prop['uav_v'] # unit: minutes
        transport_HtoH_mean_logn, transport_HtoH_std_logn = self.get_lognormal_param(transport_HtoH_mean)
        reg_prop['uav_HtoH_t'] = (transport_HtoH_mean, transport_HtoH_mean_logn, transport_HtoH_std_logn)
        # 4.병원 사이 이동 거리 중 최대값 저장
        reg_prop['uav_maxD_HtoH'] = np.max(transport_HtoH_mean_logn, None, None)
        return reg_prop

    ######### Entity 추가 template ########
    def setup_template(self, cfg):
        reg_prop = {}
        # FILL IN
        return reg_prop