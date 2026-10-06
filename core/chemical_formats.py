from __future__ import annotations

import json
import math
from pathlib import Path

from core.formats import Section


def extract_mol2(path: Path) -> list[Section]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    records = []
    current = None
    section = None
    for line_num, line in enumerate(lines, 1):
        value = line.strip()
        if value.upper() == "@<TRIPOS>MOLECULE":
            current = {"MOLECULE": []}
            records.append(current)
            section = "MOLECULE"
        elif value.upper().startswith("@<TRIPOS>"):
            if current is None:
                raise ValueError(f"MOL2 section before molecule at line {line_num}")
            section = value[9:].upper()
            if section in current:
                raise ValueError(f"Duplicate MOL2 section {section}")
            current[section] = []
        elif value and not value.startswith("#"):
            if current is None:
                raise ValueError(f"MOL2 content before molecule at line {line_num}")
            current[section].append((line_num, line))
    if not records:
        raise ValueError("No @<TRIPOS>MOLECULE records found")

    result = []
    for number, record in enumerate(records, 1):
        header = record["MOLECULE"]
        if len(header) < 4:
            raise ValueError(f"Molecule {number}: incomplete MOL2 header")
        name = header[0][1].strip()
        counts = header[1][1].split()
        if len(counts) < 2:
            raise ValueError(f"Molecule {number}: missing atom/bond counts")
        atom_count, bond_count = map(int, counts[:2])
        if atom_count < 1 or bond_count < 0:
            raise ValueError(f"Molecule {number}: invalid atom/bond counts")
        atoms = record.get("ATOM", [])
        bonds = record.get("BOND", [])
        if len(atoms) != atom_count or len(bonds) != bond_count:
            raise ValueError(f"Molecule {number}: atom/bond rows do not match header counts")
        atom_ids, bond_ids, charges = set(), set(), []
        for line_num, line in atoms:
            fields = line.split()
            if len(fields) < 6:
                raise ValueError(f"Invalid MOL2 atom at line {line_num}")
            atom_id = int(fields[0])
            if atom_id <= 0 or atom_id in atom_ids or not all(
                math.isfinite(float(value)) for value in fields[2:5]
            ):
                raise ValueError(f"Invalid MOL2 atom ID/coordinates at line {line_num}")
            atom_ids.add(atom_id)
            if len(fields) >= 9:
                charge = float(fields[8])
                if not math.isfinite(charge):
                    raise ValueError(f"Invalid MOL2 charge at line {line_num}")
                charges.append(charge)
        for line_num, line in bonds:
            fields = line.split()
            if len(fields) < 4:
                raise ValueError(f"Invalid MOL2 bond at line {line_num}")
            bond_id, atom1, atom2 = map(int, fields[:3])
            if bond_id <= 0 or bond_id in bond_ids or not {atom1, atom2} <= atom_ids:
                raise ValueError(f"Invalid MOL2 bond ID/references at line {line_num}")
            bond_ids.add(bond_id)
        summary = (
            f"Molecule {number}: {name}; atoms={atom_count}; bonds={bond_count}; "
            f"molecule_type={header[2][1].strip()}; charge_type={header[3][1].strip()}"
        )
        if len(charges) == atom_count:
            summary += f"; sum_of_partial_charges={sum(charges):.8g} (not formal charge)"
        result.append(Section(summary, f"molecule {number}, summary", number))
        schemas = {
            "ATOM": "atom_id atom_name x y z atom_type [subst_id subst_name partial_charge status]",
            "BOND": "bond_id origin_atom_id target_atom_id bond_type [status]",
        }
        for kind, rows in record.items():
            if not rows:
                continue
            prefix = summary + f"\n@<TRIPOS>{kind}"
            if kind in schemas:
                prefix += "\nColumns: " + schemas[kind]
            text = "\n".join(f"line {line_num}: {line}" for line_num, line in rows)
            result.append(Section(text, f"molecule {number}, {kind}, lines {rows[0][0]}-{rows[-1][0]}",
                                  number, prefix))
    return result


def extract_cif(path: Path) -> list[Section]:
    import gemmi

    document = gemmi.cif.read_string(path.read_text(encoding="utf-8-sig"))
    if not len(document):
        raise ValueError("CIF file contains no data blocks")
    result = []

    def value(raw):
        # Keep missing values distinct and numeric uncertainties as supplied.
        return raw if raw in ("?", ".") else json.dumps(gemmi.cif.as_string(raw), ensure_ascii=False)

    def visit(block, location, number, inherited=""):
        descriptors = [(item.pair[0], value(item.pair[1])) for item in block
                       if item.pair and (item.pair[0].startswith("_cell_")
                                         or item.pair[0].startswith("_chemical_formula"))]
        prefix = location + "\n" + ("\n".join(f"{tag} = {val}" for tag, val in descriptors) or inherited)
        for item in block:
            if item.pair:
                tag, raw = item.pair
                result.append(Section(f"{tag} = {value(raw)}", f"{location}, tag {tag}", number, prefix))
            elif item.loop:
                loop = item.loop
                tags = list(loop.tags)
                rows = []
                for row_num in range(loop.length()):
                    cells = loop.values[row_num * len(tags):(row_num + 1) * len(tags)]
                    rows.append(f"row {row_num + 1}: " + " | ".join(
                        f"{tag}={value(raw)}" for tag, raw in zip(tags, cells)
                    ))
                if rows:
                    result.append(Section("\n".join(rows), f"{location}, loop {tags[0]}", number, prefix))
            elif item.frame:
                visit(item.frame, f"{location}, save_{item.frame.name}", number, prefix)

    for number, block in enumerate(document, 1):
        visit(block, f"data_{block.name}", number)
    return result
