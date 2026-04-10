import numpy as np
import cvxpy as cp
import scipy.sparse as sp


class RobustSTL:
    """논문(RobustSTL, 2018)에 명시된 공식을 파이썬으로 구현한 알고리즘 클래스"""
    def __init__(self, y, period, reg1=1.0, reg2=0.5, K=2, H=5):
        self.y = np.array(y)
        self.period = period
        self.reg1 = reg1   # lambda_1: 추세의 1차 미분(갑작스런 변동) 정규화
        self.reg2 = reg2   # lambda_2: 추세의 2차 미분(부드러움) 정규화
        self.K = K         # 계절성 필터링 이웃 수 (수년 전 데이터까지 참고)
        self.H = H         # 계절성 필터링 윈도우 폭
        self.trend = None
        self.seasonal = None
        self.resid = None

    def bilateral_filter(self, y, H_window=5, delta_d=5.0, delta_i=None):
        """Step 1: 노이즈 제거 (Bilateral Filtering)"""
        if delta_i is None:
            delta_i = np.std(y) * 0.5 + 1e-5
        N = len(y)
        y_prime = np.zeros(N)

        coeff_d = 1.0 / (2 * delta_d**2)
        coeff_i = 1.0 / (2 * delta_i**2)

        for t in range(N):
            start = max(0, t - H_window)
            end = min(N, t + H_window + 1)
            j = np.arange(start, end)
            w = np.exp(-((j - t)**2) * coeff_d - ((y[j] - y[t])**2) * coeff_i)
            y_prime[t] = np.sum(w * y[j]) / np.sum(w)
        return y_prime

    def extract_trend(self, y_prime, T, lambda1, lambda2):
        """Step 2: L1-norm(LAD Regression) 최적화를 통한 강력한 추세 추출"""
        N = len(y_prime)
        g = y_prime[T:] - y_prime[:-T]

        diagonals_M = [np.ones(N - T) for _ in range(T)]
        offsets_M = list(range(T))
        M = sp.diags(diagonals_M, offsets_M, shape=(N - T, N - 1), format='csr')

        diagonals_D = [-np.ones(N - 2), np.ones(N - 2)]
        offsets_D = [0, 1]
        D = sp.diags(diagonals_D, offsets_D, shape=(N - 2, N - 1), format='csr')

        nabla_tau = cp.Variable(N - 1)
        objective = cp.Minimize(
            cp.norm1(g - M @ nabla_tau) +
            lambda1 * cp.norm1(nabla_tau) +
            lambda2 * cp.norm1(D @ nabla_tau)
        )
        prob = cp.Problem(objective)
        prob.solve(verbose=False)

        nabla_tau_val = nabla_tau.value
        if nabla_tau_val is None:
            nabla_tau_val = np.zeros(N - 1)

        tau_r = np.zeros(N)
        tau_r[1:] = np.cumsum(nabla_tau_val)
        return tau_r

    def extract_seasonality(self, y_double_prime, T, K, H):
        """Step 3: 비국소적 계절성 필터링 (계절성 Shift 방지)"""
        N = len(y_double_prime)
        s_tilde = np.zeros(N)
        delta_d = H / 2.0 + 1e-5
        delta_i = np.std(y_double_prime) * 0.5 + 1e-5

        coeff_d = 1.0 / (2 * delta_d**2)
        coeff_i = 1.0 / (2 * delta_i**2)

        for t in range(N):
            w_sum = 0.0
            val_sum = 0.0
            for k in range(1, K + 1):
                t_prime = t - k * T
                if t_prime < 0:
                    continue
                start = max(0, t_prime - H)
                end = min(N, t_prime + H + 1)
                j = np.arange(start, end)
                diff_y = y_double_prime[j] - y_double_prime[t]
                w = np.exp(-((j - t_prime)**2) * coeff_d - (diff_y**2) * coeff_i)
                w_sum += np.sum(w)
                val_sum += np.sum(w * y_double_prime[j])
            if w_sum > 0:
                s_tilde[t] = val_sum / w_sum
            else:
                s_tilde[t] = y_double_prime[t]
        return s_tilde

    def fit(self, iterations=1):
        """Step 4 & 5: 최종 분해 및 영점 조정 (논문에 따른 반복 순회 적용)"""
        N = len(self.y)
        self.trend = np.zeros(N)
        self.seasonal = np.zeros(N)
        current_y = self.y.copy()

        for i in range(iterations):
            y_prime = self.bilateral_filter(current_y)
            tau_r = self.extract_trend(y_prime, self.period, self.reg1, self.reg2)
            y_double_prime = y_prime - tau_r
            s_tilde = self.extract_seasonality(y_double_prime, self.period, self.K, self.H)

            valid_len = self.period * (N // self.period)
            tau_1 = np.mean(s_tilde[:valid_len]) if valid_len > 0 else 0

            self.trend += (tau_r + tau_1)
            self.seasonal += (s_tilde - tau_1)
            current_y = self.y - self.trend - self.seasonal

        self.resid = self.y - self.trend - self.seasonal
        return self
