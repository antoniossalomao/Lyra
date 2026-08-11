"""
Gera LYRA_GENESIS_V2.pdf a partir dos 3 MDs canônicos desta pasta.

Replica o estilo visual do PDF original (tema escuro, título ciano, tabelas,
badges de status coloridos, header/footer "PROJETO LYRA // RING 0"). O
conteúdo é escrito à mão neste script (não faz parsing automático dos .md) —
ao atualizar os MDs, atualize também a lista SECOES abaixo.

Uso:  python gerar_genesis_pdf.py
Saída: C:\\Lyra_Project\\LYRA_GENESIS_V2.pdf

Nota histórica: a versão anterior deste PDF tinha um bug de geração — o
retângulo de fundo era pintado DEPOIS do texto do corpo (por cima dele),
deixando todo o conteúdo das páginas invisível (só header/footer apareciam).
Este script desenha fundo -> conteúdo -> header/footer, nessa ordem.
"""
import sys
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Fontes (DejaVu — suporta acentos PT-BR e símbolos como ✓/✗) ─────────────
_MPL_FONTS = pathlib.Path(
    r"C:\Users\anton\AppData\Local\Programs\Python\Python312\Lib\site-packages"
    r"\matplotlib\mpl-data\fonts\ttf"
)
pdfmetrics.registerFont(TTFont("DV", str(_MPL_FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", str(_MPL_FONTS / "DejaVuSans-Bold.ttf")))

PAGE_W, PAGE_H = A4
MARGIN_L = 37.18
MARGIN_R = 42.52
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
TOP_Y = 813.89
BOTTOM_Y = 40

# ── Paleta (extraída do PDF original) ───────────────────────────────────────
BG        = (0.0392, 0.0392, 0.0784)   # fundo navy quase-preto
CIANO     = (0.0, 0.8667, 1.0)         # título / linhas / destaque
AZUL_CLARO= (0.7059, 0.8235, 1.0)      # subtítulos
CORPO     = (0.8627, 0.8824, 0.9216)   # texto de corpo
META      = (0.4706, 0.5098, 0.5882)   # texto pequeno/meta
LINHA_SEC = (0.1176, 0.1961, 0.3137)   # linha fina sob título de seção
VERDE     = (0.298, 0.6863, 0.3137)    # concluído / em uso
VERMELHO  = (0.898, 0.2235, 0.2078)    # aposentado / removido
AMARELO   = (0.9, 0.75, 0.2)           # planejado / pendente
CINZA_AZ  = (0.4, 0.47, 0.6)           # futuro/reservado

PAGE_TITLE = "Lyra Genesis V.2"

STATUS_COR = {"ok": VERDE, "off": VERMELHO, "wip": AMARELO, "future": CINZA_AZ}
STATUS_TXT = {"ok": "✓", "off": "✗", "wip": "○", "future": "◇"}


class Doc:
    def __init__(self, path):
        self.c = canvas.Canvas(path, pagesize=A4)
        self.page_num = 0
        self.y = 0
        self._new_page()

    # ── infraestrutura de página ────────────────────────────────────────
    def _background(self):
        c = self.c
        c.setFillColorRGB(*BG)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    def _header_footer(self):
        c = self.c
        c.setStrokeColorRGB(*CIANO)
        c.setLineWidth(0.85)
        c.line(MARGIN_L, TOP_Y, PAGE_W - MARGIN_R, TOP_Y)
        c.setFillColorRGB(0.1569, 0.1961, 0.2745)
        c.setFont("DV", 6)
        c.drawRightString(PAGE_W - MARGIN_R, TOP_Y + 6, "PROJETO LYRA // RING 0")

        c.setStrokeColorRGB(*CIANO)
        c.line(MARGIN_L, BOTTOM_Y - 12, PAGE_W - MARGIN_R, BOTTOM_Y - 12)
        c.setFillColorRGB(*META)
        c.setFont("DV", 7)
        c.drawCentredString(
            PAGE_W / 2, BOTTOM_Y - 22, f"{PAGE_TITLE} — p.{self.page_num}"
        )

    def _new_page(self):
        if self.page_num > 0:
            self._header_footer()
            self.c.showPage()
        self.page_num += 1
        self._background()
        self.y = TOP_Y - 24

    def ensure_space(self, needed):
        if self.y - needed < BOTTOM_Y + 4:
            self._new_page()

    def finish(self):
        self._header_footer()
        self.c.save()

    # ── elementos de conteúdo ───────────────────────────────────────────
    def title(self, text, meta=None):
        self.ensure_space(40)
        c = self.c
        c.setFillColorRGB(*CIANO)
        c.setFont("DV-B", 18)
        c.drawString(MARGIN_L, self.y, text)
        self.y -= 14
        c.setStrokeColorRGB(*CIANO)
        c.setLineWidth(1.42)
        c.line(MARGIN_L, self.y, MARGIN_L + CONTENT_W, self.y)
        self.y -= 10
        if meta:
            c.setFillColorRGB(*META)
            c.setFont("DV", 8.5)
            c.drawString(MARGIN_L, self.y, meta)
            self.y -= 10
            c.setStrokeColorRGB(*CIANO)
            c.setLineWidth(0.85)
            c.line(MARGIN_L, self.y, MARGIN_L + CONTENT_W, self.y)
        self.y -= 14

    def section(self, num_title):
        self.ensure_space(30)
        c = self.c
        c.setFillColorRGB(*CIANO)
        c.setFont("DV-B", 13)
        c.drawString(MARGIN_L, self.y, num_title)
        w = c.stringWidth(num_title, "DV-B", 13)
        c.setStrokeColorRGB(*LINHA_SEC)
        c.setLineWidth(0.57)
        c.line(MARGIN_L + w + 10, self.y + 4, MARGIN_L + CONTENT_W, self.y + 4)
        self.y -= 20

    def subsection(self, text, cor=AZUL_CLARO):
        self.ensure_space(20)
        c = self.c
        c.setFillColorRGB(*cor)
        c.setFont("DV-B", 10.5)
        c.drawString(MARGIN_L, self.y, text)
        self.y -= 15

    def _wrap(self, text, font, size, max_w):
        words = text.split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if pdfmetrics.stringWidth(trial, font, size) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def para(self, text, indent=0, size=8.5, cor=CORPO, leading=11.5):
        c = self.c
        max_w = CONTENT_W - indent
        for line in self._wrap(text, "DV", size, max_w):
            self.ensure_space(leading)
            c.setFillColorRGB(*cor)
            c.setFont("DV", size)
            c.drawString(MARGIN_L + indent, self.y, line)
            self.y -= leading

    def bullet(self, label, text, status=None, indent=0, size=8.5, leading=11.5):
        """Marcador — 'label' (negrito, opcional) + texto corrido, com wrap
        indentado nas linhas seguintes. 'status' pinta o marcador inicial."""
        c = self.c
        bullet_w = 14
        max_w = CONTENT_W - indent - bullet_w

        prefix = STATUS_TXT[status] + " " if status else "— "
        prefix_cor = STATUS_COR[status] if status else CORPO

        # monta a lista de "tokens" (label em negrito + texto normal) já
        # quebrada em linhas, medindo label+texto juntos como se fossem uma
        # frase só (aproximação: mede com fonte normal, label é curto)
        combined = (f"{label} " if label else "") + text
        lines = self._wrap(combined, "DV", size, max_w)

        self.ensure_space(leading)
        x0 = MARGIN_L + indent
        c.setFont("DV", size)
        c.setFillColorRGB(*prefix_cor)
        c.drawString(x0, self.y, prefix)
        x = x0 + pdfmetrics.stringWidth(prefix, "DV", size)

        first_line = lines[0] if lines else ""
        if label and first_line.startswith(label):
            c.setFont("DV-B", size)
            c.setFillColorRGB(*CIANO)
            c.drawString(x, self.y, label)
            x += pdfmetrics.stringWidth(label, "DV-B", size)
            rest = first_line[len(label):]
            c.setFont("DV", size)
            c.setFillColorRGB(*CORPO)
            c.drawString(x, self.y, rest)
        else:
            c.setFont("DV", size)
            c.setFillColorRGB(*CORPO)
            c.drawString(x, self.y, first_line)
        self.y -= leading

        for line in lines[1:]:
            self.ensure_space(leading)
            c.setFont("DV", size)
            c.setFillColorRGB(*CORPO)
            c.drawString(x0 + bullet_w, self.y, line)
            self.y -= leading

    def gap(self, h=8):
        self.y -= h

    def table(self, headers, rows, col_w, size=8.0, leading=12):
        c = self.c
        self.ensure_space(leading * 2)
        x = MARGIN_L
        c.setFont("DV-B", size)
        c.setFillColorRGB(*CIANO)
        for h, w in zip(headers, col_w):
            c.drawString(x, self.y, h)
            x += w
        self.y -= 3
        c.setStrokeColorRGB(*LINHA_SEC)
        c.setLineWidth(0.6)
        c.line(MARGIN_L, self.y, MARGIN_L + sum(col_w), self.y)
        self.y -= leading
        for row in rows:
            wrapped_cols = []
            max_lines = 1
            for cell, w in zip(row, col_w):
                lines = self._wrap(str(cell), "DV", size, w - 4)
                wrapped_cols.append(lines)
                max_lines = max(max_lines, len(lines))
            self.ensure_space(leading * max_lines)
            for li in range(max_lines):
                x = MARGIN_L
                for lines, w in zip(wrapped_cols, col_w):
                    if li < len(lines):
                        c.setFont("DV", size)
                        c.setFillColorRGB(*CORPO)
                        c.drawString(x, self.y, lines[li])
                    x += w
                self.y -= leading
        self.y -= 4

    def hr(self):
        self.ensure_space(8)
        c = self.c
        c.setStrokeColorRGB(*LINHA_SEC)
        c.setLineWidth(0.5)
        c.line(MARGIN_L, self.y, MARGIN_L + CONTENT_W, self.y)
        self.y -= 10
