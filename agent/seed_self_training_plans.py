"""
Seed Layla's first self-training cycle: 2-3 foundational study plans per domain.
Run from agent/: python seed_self_training_plans.py

- Breadth not depth; small, actionable, foundational.
- Supports cross-domain reinforcement; avoids over-specialization.
"""
import sys
from pathlib import Path

# Run from agent/
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.memory.db import get_plan_by_topic, migrate, save_study_plan  # noqa: E402

PLANS = [
    # coding (2-3)
    ("coding", "Understand async task patterns"),
    ("coding", "Practice readable function design"),
    ("coding", "Use standard library patterns first"),
    # planning (2-3)
    ("planning", "Break complex goals into steps"),
    ("planning", "Practice outlining execution paths"),
    ("planning", "Identify dependencies between tasks"),
    # writing (2-3)
    ("writing", "Explain technical ideas simply"),
    ("writing", "Practice concise summaries"),
    ("writing", "Structure docs for quick scanning"),
    # research (2-3)
    ("research", "Compare multiple sources"),
    ("research", "Evaluate source reliability"),
    ("research", "Synthesize findings into one-page summary"),
    # --- Fabrication domains (2-3 foundational each) ---
    ("cad_modeling", "Maintain fabrication-friendly geometry"),
    ("cad_modeling", "Optimize layer and object structure"),
    ("cad_modeling", "Export clean meshes for CAM and 3D print"),
    ("cam_strategy", "Compare toolpath strategies for roughing vs finishing"),
    ("cam_strategy", "Choose stepover and stepdown by material and tool"),
    ("cam_strategy", "Minimize rapid moves and optimize cut order"),
    ("parametric_design", "Build reusable parametric definitions"),
    ("parametric_design", "Control geometry through constraints"),
    ("parametric_design", "Drive dimensions from spreadsheets or code"),
    ("cnc_machining", "Compare toolpath strategies"),
    ("cnc_machining", "Understand material-specific feeds and speeds"),
    ("cnc_machining", "Set up workholding and zero points safely"),
    ("tooling", "Select tools based on geometry and material"),
    ("tooling", "Compare end mill types and coatings"),
    ("tooling", "Choose drill vs mill for holes by size and tolerance"),
    ("feeds_and_speeds", "Calculate SFM and RPM from material and tool"),
    ("feeds_and_speeds", "Adjust feed for chip load and tool life"),
    ("feeds_and_speeds", "Use conservative settings for one-off vs production"),
    ("woodworking", "Compare joint strength and use cases"),
    ("woodworking", "Choose lumber and sheet goods by project"),
    ("woodworking", "Sequence cuts for accuracy and safety"),
    ("joinery", "When to use dados, rabbets, and mortise-and-tenon"),
    ("joinery", "Layout and cut joinery by hand vs machine"),
    ("joinery", "Design for wood movement and grain direction"),
    ("structural_building", "Basic load paths and fastening for small structures"),
    ("structural_building", "When to use screws, bolts, or nails"),
    ("structural_building", "Read simple framing and assembly drawings"),
    ("furniture_design", "Proportions and ergonomics for seating and tables"),
    ("furniture_design", "Design for assembly and disassembly"),
    ("furniture_design", "Material choice and finish for durability"),
    ("digital_fabrication", "When to use laser, CNC, or 3D print for a part"),
    ("digital_fabrication", "File formats and workflows CAD to machine"),
    ("digital_fabrication", "Tolerances and fit for assembled parts"),
    ("python_fabrication_tools", "Generate DXF programmatically (ezdxf)"),
    ("python_fabrication_tools", "Analyze geometry with OpenCV"),
    ("python_fabrication_tools", "Drive CAM or toolpaths from code (e.g. G-code generation)"),
    ("fabrication_logic", "Map design intent to machine steps and materials"),
    ("fabrication_logic", "Document workflow from CAD to cut list or G-code"),
    ("fabrication_logic", "Identify bottlenecks in design-to-fabrication pipeline"),
]


def main():
    migrate()
    n_added = 0
    for i, (domain_id, topic) in enumerate(PLANS):
        if get_plan_by_topic(topic):
            continue
        plan_id = f"st-{domain_id}-{i+1}"
        save_study_plan(plan_id=plan_id, topic=topic, status="active", domain_id=domain_id)
        n_added += 1
        print(f"  + {domain_id}: {topic}")
    print(f"Seeded {n_added} new plans ({len(PLANS) - n_added} already existed).")


if __name__ == "__main__":
    main()
