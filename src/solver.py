import os

import numpy as np
import dolfin as df
from scipy import io

from designs.design_parser import parse_design
from src.filter import HelmholtzFilter
from src.problem import Problem
from src.utils import constrain

df.set_log_level(df.LogLevel.ERROR)
# turn off redundant output in parallel
df.parameters["std_out_all_processes"] = False


def expit(x):
    """Sigmoid function."""
    return 1.0 / (1.0 + np.exp(-x))


def expit_diff(x):
    """Derivative of the sigmoid function."""
    expit_val = expit(x)
    return expit_val * (1 - expit_val)


def logit(x):
    """Inverse sigmoid function."""
    return np.log(x / (1.0 - x))


class Solver:
    """Class that solves a given topology optimization problem using a magical algorithm."""

    def __init__(self, design_file: str, N: int, problem: Problem, data_path: str):
        self.problem = problem
        self.data_path = data_path
        self.design_file = design_file
        self.parameters, *extra_data = parse_design(self.design_file)

        # define domain
        self.N = N
        self.width = self.parameters.width
        self.height = self.parameters.height

        volume_fraction = self.parameters.fraction
        self.volume = self.width * self.height * volume_fraction

        self.mesh = df.Mesh(
            df.RectangleMesh(
                df.MPI.comm_world,
                df.Point(0.0, 0.0),
                df.Point(self.width, self.height),
                int(self.width * self.N),
                int(self.height * self.N),
            )
        )

        self.control_space = df.FunctionSpace(self.mesh, "DG", 0)

        self.rho = df.Function(self.control_space)
        self.rho.vector()[:] = volume_fraction

        control_filter = HelmholtzFilter(epsilon=0.02)
        self.problem.init(control_filter, self.mesh, self.parameters, extra_data)

    def project(self, half_step, volume: float):
        """
        Project half_step so the volume constraint is fulfilled by
        solving '∫expit(half_step + c)dx = volume' for c using Newton's method,
        and then adding c to half_step.
        """

        expit_integral_func = df.Function(self.control_space)
        expit_diff_integral_func = df.Function(self.control_space)

        c = 0
        max_iterations = 10
        for _ in range(max_iterations):
            expit_integral_func.vector()[:] = expit(half_step + c)
            expit_diff_integral_func.vector()[:] = expit_diff(half_step + c)

            error = float(df.assemble(expit_integral_func * df.dx) - volume)
            derivative = float(df.assemble(expit_diff_integral_func * df.dx))
            if derivative == 0.0:
                print("Warning: Got derivative equal to zero during gradient descent.")
                raise ValueError("Got derivative equal to zero while projecting psi")

            newton_step = error / derivative
            c = c - newton_step
            if abs(newton_step) < 1e-12:
                break
        else:
            print(
                "Warning: Projection reached maximum iteration "
                + "without converging. Result may not be accurate."
            )

        return half_step + c

    def step(self, previous_psi, step_size):
        """Take a entropic mirror descent step with a given step size."""
        # Latent space gradient descent
        objective_gradient = self.problem.calculate_objective_gradient().vector()[:]

        half_step = previous_psi - step_size * objective_gradient
        return self.project(half_step, self.volume)

    def step_size(self, k: int):
        return 25 * (k + 1)

    def solve(self):
        """Solve the given topology optimization problem."""
        itol = 1e-2
        ntol = 1e-5

        psi = logit(self.rho.vector()[:])
        previous_psi = None

        difference = float("Infinity")
        objective = float(self.problem.calculate_objective(self.rho))
        objective_difference = None

        print("Iteration │ Objective │ ΔObjective │     Δρ    │  Δρ-tol  ")
        print("──────────┼───────────┼────────────┼───────────┼──────────")

        def print_values(k, objective, objective_difference, difference):
            print(
                f"{k:^9} │ {constrain(objective, 9)} │ "
                + f"{constrain(objective_difference, 10)} │ "
                + f"{constrain(difference, 9)} │ "
                + f"{constrain(difference - min(self.step_size(k) * ntol, itol), 10)}",
                flush=True,
            )

        for k in range(500):
            print_values(k, objective, objective_difference, difference)
            if k % 10 == 0:
                self.save_rho(self.rho, objective, k)

            previous_psi = psi.copy()
            psi = self.step(previous_psi, self.step_size(k))

            self.rho.vector()[:] = expit(psi)
            previous_objective = objective
            objective = float(self.problem.calculate_objective(self.rho))
            objective_difference = previous_objective - objective

            if objective_difference < 0:
                print_values(k + 1, objective, objective_difference, difference)
                print("EXIT: Step increased objective value")
                break

            # create dfa functions from previous_psi to calculate difference
            previous_rho = df.Function(self.control_space)
            previous_rho.vector()[:] = expit(previous_psi)

            difference = np.sqrt(df.assemble((self.rho - previous_rho) ** 2 * df.dx))

            if difference < min(self.step_size(k) * ntol, itol):
                print_values(k + 1, objective, objective_difference, difference)
                print("EXIT: Optimal solution found")
                break
        else:
            print_values(k + 1, objective, objective_difference, difference)
            print("EXIT: Iteration did not converge")

        self.save_rho(self.rho, objective, k + 1)

    def save_rho(self, rho, objective, k):
        design = os.path.splitext(os.path.basename(self.design_file))[0]
        filename = self.data_path + f"/{design}/data/N={self.N}_{k=}.mat"

        Nx, Ny = int(self.width * self.N), int(self.height * self.N)
        data = np.array(
            [
                [rho((0.5 + xi) / self.N, (0.5 + yi) / self.N) for xi in range(Nx)]
                for yi in range(Ny)
            ]
        )

        os.makedirs(os.path.dirname(filename), exist_ok=True)
        io.savemat(
            filename,
            mdict={
                "data": data,
                "objective": objective,
            },
        )
