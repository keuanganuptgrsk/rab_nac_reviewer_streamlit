def generate_suggestion(text, keyword="", category="", confidence=0, allowable_score=0, exception_hit=False):
    text_l = (text or "").lower()
    item = _short_item(text)
    if exception_hit or ("konsumsi" in text_l and ("bahan bakar" in text_l or "genset" in text_l)):
        return (
            "Usulan redaksi: Konsumsi bahan bakar untuk peralatan/operasi teknis [lokasi/peralatan]. "
            "Lampirkan dasar kebutuhan dan bukti pemakaian; pertimbangkan exception jika pola ini berulang."
        )
    if any(token in text_l for token in ["fee narasumber", "honor narasumber", "penceramah", "narasumber"]):
        return (
            "Usulan redaksi: Jasa narasumber/pemateri untuk kegiatan teknis [nama kegiatan], "
            "dengan output [materi/berita acara/laporan] dan dasar penugasan [referensi]. "
            "Jika tidak terkait langsung dengan pekerjaan teknis/allowable, pisahkan dari perhitungan allowable."
        )
    if any(token in text_l for token in ["doorprize", "hadiah", "oleh-oleh", "souvenir", "cinderamata", "bawaan"]):
        return (
            f"Usulan redaksi: {item} - klarifikasi tujuan, penerima, dasar kegiatan, dan output. "
            "Jika merupakan hadiah/souvenir/representasi yang tidak allowable, pisahkan dari komponen allowable."
        )
    if any(token in text_l for token in ["baju vip", "seragam non teknis", "songkok", "sandal"]):
        return (
            "Usulan redaksi: Perlengkapan/pakaian untuk kebutuhan kegiatan teknis [fungsi dan penerima]. "
            "Jika bersifat pribadi, seremonial, atau non-teknis, pisahkan dari komponen allowable."
        )
    if "perjalanan" in text_l or "transport" in text_l:
        return (
            "Usulan redaksi: Transportasi kegiatan teknis [lokasi/tujuan] berdasarkan [surat tugas/work order], "
            "dengan output [laporan/BA inspeksi] dan unit penanggung jawab [unit]."
        )
    if any(token in text_l for token in ["konsumsi", "jamuan", "snack", "coffee", "catering", "prasmanan", "minuman", "makan"]):
        return (
            "Usulan redaksi: Konsumsi pendukung kegiatan teknis [nama kegiatan] pada [tanggal/lokasi], "
            "untuk peserta [daftar peserta] dengan output [BA/laporan]. Jika tidak memenuhi dasar allowable, pisahkan dari komponen allowable."
        )
    if confidence >= 45:
        return (
            f"Usulan redaksi: {item} untuk ruang lingkup teknis [uraian pekerjaan], "
            "berdasarkan [PMK/kebijakan internal/work order], dengan output [deliverable]. "
            "Pisahkan komponen non-allowable bila bercampur dan minta review manual."
        )
    if allowable_score > 50:
        return "Usulan redaksi: Pertahankan konteks teknis secara eksplisit dan lampirkan dokumen pendukung untuk audit."
    return "Tidak ada saran redaksi khusus. Lakukan review manual bila konteks pekerjaan belum jelas."


def recommended_action(confidence, allowable_score=0):
    if confidence >= 65 and allowable_score >= 60:
        return "Perlu Review Manual"
    if confidence >= 85:
        return "Potensi NAC tinggi - validasi reviewer dan pisahkan komponen bila perlu"
    if confidence >= 45:
        return "Perlu Review Manual"
    return "Monitor / dokumentasikan konteks"


def _short_item(text):
    parts = [part.strip() for part in str(text or "").split("|") if part.strip()]
    item = parts[-1] if parts else str(text or "").strip()
    if len(item) > 80:
        return item[:77].rstrip() + "..."
    return item or "Item RAB"
