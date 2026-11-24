import io
from datetime import datetime

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


def _pdf_safe_text(text):
    if text is None:
        return ""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def build_results_pdf_bytes(wines, leaderboard, carafe_details, wine_stats, stats):
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if HAS_FPDF:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_fill_color(76, 5, 25)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, _pdf_safe_text("Blind Wine - Résultats Globaux"), ln=True, align="C", fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, _pdf_safe_text(f"Exporté le {date_str}"), ln=True, align="C")
        pdf.ln(3)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("1. Statistiques de la soirée"), ln=True)
        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _pdf_safe_text(
            f"Participants : {stats['total_players']}   |   Carafes : {stats['total_wines']}   |   "
            f"Réussite globale : {stats['global_success_rate']}% ({stats['total_correct_votes']}/{stats['total_possible_votes']})"
        ), ln=True)
        if stats['hardest_wine']:
            hw = stats['hardest_wine']
            pdf.cell(0, 6, _pdf_safe_text(
                f"Vin le plus piégeux : Carafe N°{hw['carafe_number']} - {hw['name']} ({hw['correct_count']}/{hw['total_players']} trouvés)"
            ), ln=True)
        if stats['easiest_wine']:
            ew = stats['easiest_wine']
            pdf.cell(0, 6, _pdf_safe_text(
                f"Vin le plus reconnu : Carafe N°{ew['carafe_number']} - {ew['name']} ({ew['correct_count']}/{ew['total_players']} trouvés)"
            ), ln=True)
        pdf.ln(4)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("2. Classement des nez"), ln=True)

        pdf.set_fill_color(245, 240, 240)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(20, 8, _pdf_safe_text("Rang"), border=1, align="C", fill=True)
        pdf.cell(85, 8, _pdf_safe_text("Joueur"), border=1, fill=True)
        pdf.cell(40, 8, _pdf_safe_text("Vins trouvés"), border=1, align="C", fill=True)
        pdf.cell(45, 8, _pdf_safe_text("Score pondéré"), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 10)
        for p in leaderboard:
            rank_label = "1er" if p['rank'] == 1 else f"{p['rank']}e"
            pdf.cell(20, 7, _pdf_safe_text(rank_label), border=1, align="C")
            pdf.cell(85, 7, _pdf_safe_text(p['username']), border=1)
            pdf.cell(40, 7, _pdf_safe_text(f"{p['score']} / {p['total']}"), border=1, align="C")
            pdf.cell(45, 7, _pdf_safe_text(f"{p['weighted_score']} pts"), border=1, align="C")
            pdf.ln()
        pdf.ln(4)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("3. La vérité sur les carafes"), ln=True)

        pdf.set_fill_color(245, 240, 240)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(22, 7, _pdf_safe_text("Carafe"), border=1, align="C", fill=True)
        pdf.cell(88, 7, _pdf_safe_text("Vin (Millésime / Région)"), border=1, fill=True)
        pdf.cell(28, 7, _pdf_safe_text("Trouvé"), border=1, align="C", fill=True)
        pdf.cell(26, 7, _pdf_safe_text("Note moy."), border=1, align="C", fill=True)
        pdf.cell(26, 7, _pdf_safe_text("Poids"), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        for ws in wine_stats:
            w_obj = next((x for x in wines if x['carafe_number'] == ws['carafe_number']), None)
            extra = []
            if ws['year']:
                extra.append(str(ws['year']))
            if w_obj and w_obj['region']:
                extra.append(str(w_obj['region']))
            label = ws['name'] + (f" ({' - '.join(extra)})" if extra else "")
            avg_str = f"{ws['avg_rating']}/10" if ws['avg_rating'] is not None else "-"
            pdf.cell(22, 7, _pdf_safe_text(f"N°{ws['carafe_number']}"), border=1, align="C")
            pdf.cell(88, 7, _pdf_safe_text(label[:52]), border=1)
            pdf.cell(28, 7, _pdf_safe_text(f"{ws['correct_count']}/{ws['total_players']} ({ws['success_rate']}%)"), border=1, align="C")
            pdf.cell(26, 7, _pdf_safe_text(avg_str), border=1, align="C")
            pdf.cell(26, 7, _pdf_safe_text(f"{ws['weight']} pts"), border=1, align="C")
            pdf.ln()

        raw = pdf.output()
        return bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw.encode("latin-1")

    lines = [
        f"BLIND WINE - RESULTATS GLOBAUX ({date_str})",
        "=" * 60,
        f"Participants: {stats['total_players']} | Carafes: {stats['total_wines']} | Reussite: {stats['global_success_rate']}%",
        "",
        "CLASSEMENT GENERAL :",
    ]
    for p in leaderboard:
        lines.append(f"  #{p['rank']} {p['username']} : {p['score']}/{p['total']} ({p['weighted_score']} pts)")
    lines.append("")
    lines.append("VERITE SUR LES CARAFES :")
    for ws in wine_stats:
        lines.append(f"  Carafe N°{ws['carafe_number']} -> {ws['name']} ({ws['correct_count']}/{ws['total_players']}, poids {ws['weight']} pts)")

    def _esc(s):
        return _pdf_safe_text(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    pages_lines = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [["Aucun resultat"]]
    objects = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"]
    page_ids = []
    next_id = 4
    page_objs = []
    for plines in pages_lines:
        content_ops = ["BT", "/F1 10 Tf", "40 800 Td", "14 TL"]
        for ln in plines:
            content_ops.append(f"({_esc(ln)}) Tj T*")
        content_ops.append("ET")
        stream = "\n".join(content_ops).encode("latin-1", "replace")
        p_id = next_id
        c_id = next_id + 1
        next_id += 2
        page_ids.append(p_id)
        page_objs.append(
            f"{p_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {c_id} 0 R >> endobj\n".encode("ascii")
        )
        page_objs.append(
            f"{c_id} 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n"
        )

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"2 0 obj << /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >> endobj\n".encode("ascii"))
    objects.append(b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.extend(page_objs)

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return buf.getvalue()