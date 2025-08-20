# 고정 파라미터 (make_csv_yaml.py 기반)
FIXED_PARAMS = {
    "incident_size": 30,
    "uav_size": 3,
    "ambulance_count": 30,
    "ratio_dict": {"Red": 0.1, "Yellow": 0.3, "Green": 0.5, "Black": 0.1},
    "rescue_param_dict": {"Red": (6, 5), "Yellow": (2, 13), "Green": (1, 22), "Black": (0, 0)},
    "treat_tier1_dict": {"Red": True, "Yellow": True, "Green": True, "Black": True},
    "treat_tier2_dict": {"Red": False, "Yellow": True, "Green": True, "Black": True},
    "treat_tier1_mean_dict": {"Red": 40, "Yellow": 20, "Green": 10, "Black": 0},
    "treat_tier2_mean_dict": {"Red": 60, "Yellow": 30, "Green": 15, "Black": 0},
}
