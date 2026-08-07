"""ISA 표준대기 상수 (도메인 문서 01§2.5).

WGS-84 지구모델 상수는 plant(M5) 착수 시 이 모듈에 추가한다.
"""

ISA_T0 = 288.15  # 해면 표준온도 [K]
ISA_P0 = 101325.0  # 해면 표준압력 [Pa]
ISA_RHO0 = 1.225  # 해면 표준밀도 [kg/m3]
ISA_LAPSE_RATE = -0.0065  # 대류권 기온감률 [K/m]
ISA_R_AIR = 287.05287  # 건조공기 비기체상수 [J/(kg·K)]
ISA_GAMMA_AIR = 1.4  # 비열비 [-]
ISA_TROPOPAUSE_ALT = 11000.0  # 대류권계면 고도 [m, 지오퍼텐셜]
ISA_STRATO1_TOP_ALT = 20000.0  # 등온 성층권 1층 상한 고도 [m, 지오퍼텐셜]
ISA_MIN_ALT = -5000.0  # 모델 유효 하한 고도 [m, 지오퍼텐셜]
