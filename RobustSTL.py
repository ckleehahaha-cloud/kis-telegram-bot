import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog


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
        """Step 2: L1-norm(LAD Regression) 최적화를 통한 강력한 추세 추출

        LP reformulation:
          min  1ᵀu + λ₁·1ᵀv + λ₂·1ᵀw
          s.t.  u ≥  g - M·∇τ,  u ≥ -(g - M·∇τ)   (||g - M∇τ||₁)
                v ≥  ∇τ,         v ≥ -∇τ             (||∇τ||₁)
                w ≥  D·∇τ,       w ≥ -D·∇τ           (||D∇τ||₁)
                u, v, w ≥ 0;  ∇τ free
        Decision vector x = [∇τ (Np), u (K), v (Np), w (Nd)]
        where Np = N-1, K = N-T, Nd = N-2.
        """
        N = len(y_prime)
        g = y_prime[T:] - y_prime[:-T]

        Np = N - 1   # size of ∇τ
        K  = N - T   # rows of M  (= len(g))
        Nd = N - 2   # rows of D

        diagonals_M = [np.ones(K) for _ in range(T)]
        offsets_M = list(range(T))
        M = sp.diags(diagonals_M, offsets_M, shape=(K, Np), format='csr')

        diagonals_D = [-np.ones(Nd), np.ones(Nd)]
        offsets_D = [0, 1]
        D = sp.diags(diagonals_D, offsets_D, shape=(Nd, Np), format='csr')

        # Objective: min 1ᵀu + λ₁·1ᵀv + λ₂·1ᵀw  (∇τ coefficients = 0)
        c = np.concatenate([
            np.zeros(Np),
            np.ones(K),
            lambda1 * np.ones(Np),
            lambda2 * np.ones(Nd),
        ])

        # Build A_ub · x ≤ b_ub in sparse blocks
        # Indices: ∇τ[0:Np], u[Np:Np+K], v[Np+K:Np+K+Np], w[Np+K+Np:end]
        z_Kp  = sp.csr_matrix((K,  Np))
        z_Kk  = sp.csr_matrix((K,  K))
        z_Knp = sp.csr_matrix((K,  Np))
        z_Kd  = sp.csr_matrix((K,  Nd))

        z_Npp = sp.csr_matrix((Np, Np))
        z_Npk = sp.csr_matrix((Np, K))
        z_Npd = sp.csr_matrix((Np, Nd))
        I_Np  = sp.eye(Np, format='csr')

        z_Dp  = sp.csr_matrix((Nd, Np))
        z_Dk  = sp.csr_matrix((Nd, K))
        z_Dnp = sp.csr_matrix((Nd, Np))
        I_Nd  = sp.eye(Nd, format='csr')
        I_K   = sp.eye(K,  format='csr')

        # Row block 1:  M·∇τ - u ≤ g   →  [M | -I_K | 0 | 0]
        # Row block 2: -M·∇τ - u ≤ -g   →  [-M | -I_K | 0 | 0]
        # Row block 3:  ∇τ - v ≤ 0      →  [I | 0 | -I | 0]
        # Row block 4: -∇τ - v ≤ 0      →  [-I | 0 | -I | 0]
        # Row block 5:  D·∇τ - w ≤ 0    →  [D | 0 | 0 | -I_Nd]
        # Row block 6: -D·∇τ - w ≤ 0    →  [-D | 0 | 0 | -I_Nd]

        A_ub = sp.bmat([
            [ M,  -I_K,  z_Knp,  z_Kd],
            [-M,  -I_K,  z_Knp,  z_Kd],
            [ I_Np, z_Npk, -I_Np, z_Npd],
            [-I_Np, z_Npk, -I_Np, z_Npd],
            [ D,  z_Dk,  z_Dp,  -I_Nd],
            [-D,  z_Dk,  z_Dp,  -I_Nd],
        ], format='csr')

        b_ub = np.concatenate([g, -g,
                               np.zeros(Np), np.zeros(Np),
                               np.zeros(Nd), np.zeros(Nd)])

        # Bounds: ∇τ free, u/v/w ≥ 0
        bounds = ([(None, None)] * Np +
                  [(0, None)] * K  +
                  [(0, None)] * Np +
                  [(0, None)] * Nd)

        res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs',
                      options={'disp': False})

        if res.success:
            nabla_tau_val = res.x[:Np]
        else:
            nabla_tau_val = np.zeros(Np)

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
