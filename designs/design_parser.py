from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
import json


class Side(Enum):
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()

    @classmethod
    def from_string(cls, string: str):
        if string == "left":
            return cls.LEFT
        elif string == "right":
            return cls.RIGHT
        elif string == "top":
            return cls.TOP
        elif string == "bottom":
            return cls.BOTTOM
        else:
            print(f"Side.from_string: Malformed side: '{string}'")
            print(f"Legal sides are: 'left', ''right', 'top' or 'bottom'")
            raise ValueError(f"Malformed side: '{string}'")


@dataclass
class SolverParameters:
    problem: str
    objective: str
    width: float
    height: float
    fraction: float


@dataclass
class Flow:
    side: Side
    center: float
    length: float
    rate: float

    def __iter__(self):
        return iter((self.side, self.center, self.length, self.rate))


@dataclass
class Region:
    center: tuple[float, float]
    size: tuple[float, float]


@dataclass
class ForceRegion:
    radius: float
    center: tuple[float, float]
    value: tuple[float, float]


@dataclass
class Traction:
    side: Side
    center: float
    length: float
    value: tuple[float, float]

    def __iter__(self):
        return iter((self.side, self.center, self.length, self.value))


def to_tuple(ray: list[float], length: int):
    if len(ray) != length:
        print(
            f"Got array that should have had {length} elements, "
            + f"but had {len(ray)} instead: '{ray}'"
        )
        raise ValueError(f"Malformed list: '{ray}'")

    return tuple([float(v) for v in ray])


def get_elasticity_arguments(design):
    force_region = None
    if region := design.get("force_region"):
        force_region = ForceRegion(
            float(region["radius"]),
            to_tuple(region["center"], 2),
            to_tuple(region["value"], 2),
        )

    fixed_sides: list[Side] = []
    for side in design["fixed_sides"]:
        fixed_sides.append(Side.from_string(side))

    tractions: list[Traction] = []
    if design_tractions := design.get("tractions"):
        for traction in design_tractions:
            tractions.append(
                Traction(
                    Side.from_string(traction["side"]),
                    float(traction["center"]),
                    float(traction["length"]),
                    to_tuple(traction["value"], 2),
                )
            )

    return force_region, fixed_sides, tractions


def get_fluid_arguments(design):
    flows: list[Flow] = []
    for flow_dict in design["flows"]:
        flows.append(
            Flow(
                Side.from_string(flow_dict["side"]),
                flow_dict["center"],
                flow_dict["length"],
                flow_dict["rate"],
            )
        )

    if len(design.get("zero_pressure", [])) == 0:
        total_flow = 0
        for flow in flows:
            total_flow += flow.rate * flow.length

        if abs(total_flow) > 1e-14:
            print(f"Error: Illegal design: total flow is {total_flow}, not 0!")
            exit(1)

    no_slip = None
    if design.get("no_slip"):
        sides: list[Side] = []
        for side in design["no_slip"]:
            sides.append(Side.from_string(side))
        no_slip = sides

    zero_pressure = None
    if design.get("zero_pressure"):
        sides: list[Side] = []
        for side in design["zero_pressure"]:
            sides.append(Side.from_string(side))
        zero_pressure = sides

    max_region = None
    if design.get("max_region"):
        center = design["max_region"]["center"]
        cx, cy = float(center[0]), float(center[1])

        size = design["max_region"]["size"]
        w, h = float(size[0]), float(size[1])

        max_region = Region((cx, cy), (w, h))
    elif design["objective"] == "maximize_flow":
        print("Error: Got maximize flow objective with no max region!")
        exit(1)

    return flows, no_slip, zero_pressure, max_region


def parse_design(filename: str):
    with open(filename, "r") as design_file:
        design = json.load(design_file)

    legal_objectives = ["minimize_power", "maximize_flow", "minimize_compliance"]
    if not design["objective"] in legal_objectives:
        print(f"Error: Got design with malformed objective: '{design['objective']}'")
        print(f"Legal objectives are: {', '.join(legal_objectives)}")
        exit(1)

    parameters = SolverParameters(
        design["problem"],
        design["objective"],
        design["width"],
        design["height"],
        design["fraction"],
    )

    if design["problem"] == "elasticity":
        return parameters, *get_elasticity_arguments(design)
    else:
        return parameters, *get_fluid_arguments(design)


if __name__ == "__main__":
    parameters, flows, no_slip, zero_pressure, max_region = parse_design(
        "designs/fluid_mechanism.json"
    )
    print(parameters)
    print(flows)
    print(no_slip)
    print(zero_pressure)
    print(max_region)
