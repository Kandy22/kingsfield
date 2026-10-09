"""
maxent_panel.py — Pairwise maximum-entropy (Ising) model for multi-judge voting panels.

Valid target: a FIXED panel of N judges voting on the SAME cases, repeatedly.
State supreme courts and en banc appellate panels qualify. Trial judges sitting
alone do not. Social media activity does not (no shared question, no simultaneity).

Model:
    p(s) = exp( sum_i h_i s_i  +  sum_{i<j} J_ij s_i s_j ) / Z
    s in {-1,+1}^N

h_i  = individual bias (how a judge votes absent peer effects)
J_ij = pairwise alignment (positive = co-voting beyond what individual bias explains)

Fitting is exact maximum likelihood by enumerating all 2^N states. For N <= 16 this
is cheap and avoids the approximation error of pseudolikelihood or MCMC. Gradients:
    dL/dh_i  = <s_i>_data      - <s_i>_model
    dL/dJ_ij = <s_i s_j>_data  - <s_i s_j>_model

Includes:
  1. recovery_test()      — fit synthetic data with KNOWN couplings, verify they come back
  2. sample_size_curve()  — how many joint observations you need before J is meaningful
  3. independence_gain()  — does the pairwise model beat an independent-votes model at all
  4. load_scdb()          — loader for Supreme Court Database justice-centered CSV

Nothing here reports findings about real judges. It reports whether the estimator works.
"""

from __future__ import annotations

import itertools
import numpy as np
from scipy.optimize import minimize


# ----------------------------------------------------------------------
# core model
# ----------------------------------------------------------------------

class IsingPanel:
    """Pairwise MaxEnt model over N binary voters, fit by exact MLE."""

    def __init__(self, n: int, l2: float = 0.0):
        if n > 16:
            raise ValueError(f"exact enumeration needs N<=16, got {n}")
        self.n = n
        self.l2 = l2
        self.pairs = list(itertools.combinations(range(n), 2))
        # all 2^N states as a (2^N, N) matrix of +/-1
        self.states = np.array(
            list(itertools.product([-1, 1], repeat=n)), dtype=np.float64
        )
        # precompute s_i*s_j for every state/pair -> (2^N, n_pairs)
        self.state_pairs = np.column_stack(
            [self.states[:, i] * self.states[:, j] for i, j in self.pairs]
        )
        self.h_ = None
        self.J_ = None

    # -- parameter packing -------------------------------------------------

    def _unpack(self, theta):
        return theta[: self.n], theta[self.n:]

    def _energy_terms(self, h, j):
        """Unnormalized log-probability of every state."""
        return self.states @ h + self.state_pairs @ j

    def _model_moments(self, h, j):
        """Return (<s_i>, <s_i s_j>, logZ) under the model."""
        e = self._energy_terms(h, j)
        m = e.max()
        w = np.exp(e - m)
        z = w.sum()
        p = w / z
        return self.states.T @ p, self.state_pairs.T @ p, m + np.log(z)

    # -- fitting -----------------------------------------------------------

    def fit(self, S: np.ndarray, verbose: bool = False):
        """
        S : (n_samples, n) array of +/-1 votes. One row per case.
        """
        S = np.asarray(S, dtype=np.float64)
        if S.shape[1] != self.n:
            raise ValueError(f"expected {self.n} columns, got {S.shape[1]}")

        emp_si = S.mean(axis=0)
        emp_sisj = np.array([(S[:, i] * S[:, j]).mean() for i, j in self.pairs])

        def negloglik(theta):
            h, j = self._unpack(theta)
            mod_si, mod_sisj, logz = self._model_moments(h, j)
            ll = emp_si @ h + emp_sisj @ j - logz
            grad = np.concatenate([emp_si - mod_si, emp_sisj - mod_sisj])
            if self.l2:
                ll -= self.l2 * (theta @ theta)
                grad -= 2 * self.l2 * theta
            return -ll, -grad

        theta0 = np.zeros(self.n + len(self.pairs))
        res = minimize(negloglik, theta0, jac=True, method="L-BFGS-B",
                       options={"maxiter": 2000, "ftol": 1e-14, "gtol": 1e-10})
        if verbose:
            print(f"  converged={res.success}  nll={res.fun:.6f}  iters={res.nit}")

        self.h_, self.J_ = self._unpack(res.x)
        self._emp_si, self._emp_sisj = emp_si, emp_sisj
        self._n_samples = S.shape[0]
        return self

    # -- sampling ----------------------------------------------------------

    def sample(self, n_samples: int, rng: np.random.Generator) -> np.ndarray:
        """Exact sampling from the fitted (or supplied) distribution."""
        e = self._energy_terms(self.h_, self.J_)
        p = np.exp(e - e.max())
        p /= p.sum()
        idx = rng.choice(len(self.states), size=n_samples, p=p)
        return self.states[idx]

    def set_params(self, h, J):
        self.h_, self.J_ = np.asarray(h, float), np.asarray(J, float)
        return self

    # -- diagnostics -------------------------------------------------------

    def J_matrix(self) -> np.ndarray:
        M = np.zeros((self.n, self.n))
        for k, (i, j) in enumerate(self.pairs):
            M[i, j] = M[j, i] = self.J_[k]
        return M

    def loglik_per_sample(self, S: np.ndarray) -> float:
        S = np.asarray(S, float)
        _, _, logz = self._model_moments(self.h_, self.J_)
        si = S.mean(axis=0)
        sisj = np.array([(S[:, i] * S[:, j]).mean() for i, j in self.pairs])
        return si @ self.h_ + sisj @ self.J_ - logz


def independent_loglik(S: np.ndarray) -> float:
    """Log-likelihood per sample of the best independent (no-coupling) model."""
    S = np.asarray(S, float)
    m = np.clip(S.mean(axis=0), -0.999999, 0.999999)
    p_up = (1 + m) / 2
    ll = 0.0
    for i in range(S.shape[1]):
        up = (S[:, i] > 0).mean()
        ll += up * np.log(p_up[i]) + (1 - up) * np.log(1 - p_up[i])
    return ll


# ----------------------------------------------------------------------
# 1. does the solver actually recover known couplings?
# ----------------------------------------------------------------------

def recovery_test(n=7, n_samples=2000, seed=0, l2=0.0):
    rng = np.random.default_rng(seed)
    truth = IsingPanel(n)
    h_true = rng.normal(0, 0.4, n)
    J_true = rng.normal(0, 0.3, len(truth.pairs))
    truth.set_params(h_true, J_true)

    S = truth.sample(n_samples, rng)
    fit = IsingPanel(n, l2=l2).fit(S)

    r_h = np.corrcoef(h_true, fit.h_)[0, 1]
    r_J = np.corrcoef(J_true, fit.J_)[0, 1]
    return {
        "n": n, "n_samples": n_samples,
        "corr_h": r_h, "corr_J": r_J,
        "max_abs_err_J": np.abs(J_true - fit.J_).max(),
        "rmse_J": float(np.sqrt(((J_true - fit.J_) ** 2).mean())),
    }


# ----------------------------------------------------------------------
# 2. how many joint observations do you need?
# ----------------------------------------------------------------------

def sample_size_curve(n=7, sizes=(25, 50, 100, 250, 500, 1000, 2500, 5000),
                      reps=8, seed=1, l2=0.0):
    rng = np.random.default_rng(seed)
    truth = IsingPanel(n)
    out = []
    for m in sizes:
        rs, es = [], []
        for _ in range(reps):
            h_true = rng.normal(0, 0.4, n)
            J_true = rng.normal(0, 0.3, len(truth.pairs))
            truth.set_params(h_true, J_true)
            S = truth.sample(m, rng)
            f = IsingPanel(n, l2=l2).fit(S)
            rs.append(np.corrcoef(J_true, f.J_)[0, 1])
            es.append(np.sqrt(((J_true - f.J_) ** 2).mean()))
        out.append({"n_samples": m,
                    "corr_J_mean": float(np.mean(rs)),
                    "corr_J_sd": float(np.std(rs)),
                    "rmse_J_mean": float(np.mean(es))})
    return out


# ----------------------------------------------------------------------
# 3. is the pairwise model worth it over independence?
# ----------------------------------------------------------------------

def independence_gain(S: np.ndarray, l2: float = 0.0):
    S = np.asarray(S, float)
    n = S.shape[1]
    f = IsingPanel(n, l2=l2).fit(S)
    ll_pair = f.loglik_per_sample(S)
    ll_ind = independent_loglik(S)
    return {"loglik_pairwise": float(ll_pair),
            "loglik_independent": float(ll_ind),
            "gain_nats_per_case": float(ll_pair - ll_ind)}


# ----------------------------------------------------------------------
# 4. real data loader — Supreme Court Database, justice-centered file
# ----------------------------------------------------------------------

def load_scdb(path: str, spin: str = "direction", min_term: int | None = None):
    """
    Build a (n_cases, n_justices) +/-1 vote matrix from the SCDB justice-centered CSV.

    spin='direction' : SCDB `direction` (1=conservative -> -1, 2=liberal -> +1)
                       Ideological coding. Comparable across cases.
    spin='majority'  : SCDB `majority` (1=dissent -> -1, 2=majority -> +1)
                       Outcome-relative; couplings then measure bloc cohesion,
                       not ideological alignment. The choice changes what J means.

    Only rows where every justice on the fixed panel voted are kept, because the
    model requires complete joint observations. Panel turnover is why you must
    restrict to a natural-court period (a span with stable membership).
    """
    import pandas as pd

    df = pd.read_csv(path, encoding="latin-1", low_memory=False)
    col = {"direction": "direction", "majority": "majority"}[spin]
    if min_term is not None:
        df = df[df["term"] >= min_term]

    df = df[["caseId", "justiceName", col]].dropna()
    wide = df.pivot_table(index="caseId", columns="justiceName",
                          values=col, aggfunc="first")
    wide = wide.dropna(axis=0, how="any")          # complete joint observations only
    S = np.where(wide.values == 2, 1.0, -1.0)
    return S, list(wide.columns)


# ----------------------------------------------------------------------

if __name__ == "__main__":
    np.set_printoptions(precision=3, suppress=True)

    print("=" * 68)
    print("1. RECOVERY TEST — can the solver recover couplings it was given?")
    print("=" * 68)
    for m in (200, 1000, 5000):
        r = recovery_test(n=7, n_samples=m)
        print(f"  N=7  M={m:>5}   corr(J_true,J_fit)={r['corr_J']:.3f}   "
              f"RMSE={r['rmse_J']:.3f}   max err={r['max_abs_err_J']:.3f}")

    print()
    print("=" * 68)
    print("2. SAMPLE SIZE — joint observations needed for N=7 (21 couplings)")
    print("=" * 68)
    for row in sample_size_curve(n=7):
        print(f"  M={row['n_samples']:>5}   corr(J)={row['corr_J_mean']:.3f} "
              f"(sd {row['corr_J_sd']:.3f})   RMSE={row['rmse_J_mean']:.3f}")

    print()
    print("=" * 68)
    print("3. PAIRWISE vs INDEPENDENT — does coupling buy anything?")
    print("=" * 68)
    rng = np.random.default_rng(7)
    truth = IsingPanel(7)
    truth.set_params(rng.normal(0, 0.4, 7), rng.normal(0, 0.5, 21))
    S = truth.sample(3000, rng)
    g = independence_gain(S)
    print(f"  coupled court   : {g['gain_nats_per_case']:.4f} nats/case gain")

    truth.set_params(rng.normal(0, 0.4, 7), np.zeros(21))   # no true coupling
    S0 = truth.sample(3000, rng)
    g0 = independence_gain(S0)
    print(f"  uncoupled court : {g0['gain_nats_per_case']:.4f} nats/case gain")
    print("  (near-zero on the uncoupled court is the control: the statistic")
    print("   does not manufacture structure that isn't there)")
