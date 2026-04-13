"""Tool implementations — domain: analysis."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def regex_test(pattern: str, text: str, flags: str = "") -> dict:
    """Test a regex pattern against text. Returns matches, groups, count."""
    try:
        import re as _re
        flag_map = {"i": _re.IGNORECASE, "m": _re.MULTILINE, "s": _re.DOTALL}
        compiled_flags = 0
        for f in flags.lower():
            compiled_flags |= flag_map.get(f, 0)
        rx = _re.compile(pattern, compiled_flags)
        matches = list(rx.finditer(text))
        result = []
        for m in matches[:20]:
            result.append({"match": m.group(0), "start": m.start(), "end": m.end(), "groups": list(m.groups())})
        return {"ok": True, "count": len(matches), "matches": result, "pattern": pattern}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def math_eval(expression: str) -> dict:
    """
    Safely evaluate a mathematical expression. Supports: +, -, *, /, **, %, //, abs, round,
    min, max, sum, int, float, sqrt, log, sin, cos, tan, pi, e, and more.
    No arbitrary code execution — uses a strict AST whitelist.
    """
    import ast as _ast
    import math as _math
    import operator as _op

    _SAFE_NODES = (
        _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Call, _ast.Constant,
        _ast.Add, _ast.Sub, _ast.Mul, _ast.Div, _ast.Pow, _ast.Mod, _ast.FloorDiv,
        _ast.UAdd, _ast.USub, _ast.Compare, _ast.Lt, _ast.Gt, _ast.LtE, _ast.GtE,
        _ast.Eq, _ast.NotEq, _ast.BoolOp, _ast.And, _ast.Or, _ast.Name, _ast.List,
        _ast.Tuple,
    )
    _SAFE_FUNCS = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "int": int, "float": float, "bool": bool,
        "sqrt": _math.sqrt, "log": _math.log, "log2": _math.log2, "log10": _math.log10,
        "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
        "asin": _math.asin, "acos": _math.acos, "atan": _math.atan, "atan2": _math.atan2,
        "ceil": _math.ceil, "floor": _math.floor, "trunc": _math.trunc,
        "factorial": _math.factorial, "gcd": _math.gcd,
        "degrees": _math.degrees, "radians": _math.radians,
        "pi": _math.pi, "e": _math.e, "tau": _math.tau, "inf": _math.inf,
        "pow": pow, "divmod": divmod,
    }

    def _safe_eval(node):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"Disallowed operation: {type(node).__name__}")
        if isinstance(node, _ast.Constant):
            return node.value
        if isinstance(node, _ast.Name):
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, _ast.BinOp):
            ops = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mul: _op.mul,
                   _ast.Div: _op.truediv, _ast.Pow: _op.pow, _ast.Mod: _op.mod,
                   _ast.FloorDiv: _op.floordiv}
            return ops[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
        if isinstance(node, _ast.UnaryOp):
            ops = {_ast.UAdd: _op.pos, _ast.USub: _op.neg}
            return ops[type(node.op)](_safe_eval(node.operand))
        if isinstance(node, _ast.Call):
            func = _safe_eval(node.func)
            args = [_safe_eval(a) for a in node.args]
            return func(*args)
        if isinstance(node, (_ast.List, _ast.Tuple)):
            return [_safe_eval(el) for el in node.elts]
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    try:
        tree = _ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree.body)
        return {"ok": True, "expression": expression, "result": result, "result_str": str(result)}
    except ZeroDivisionError:
        return {"ok": False, "error": "Division by zero"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def count_tokens(text: str, model: str = "gpt-4") -> dict:
    """
    Count tokens in text. Uses tiktoken (cl100k_base) when available.
    model hint used for encoding_for_model when supported; falls back to cl100k_base.
    """
    try:
        from services.token_count import count_tokens as _count
        from services.token_count import token_count_available
        if token_count_available():
            n = _count(text)
            return {"ok": True, "tokens": n, "model": "cl100k_base", "method": "tiktoken"}
    except Exception:
        pass
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(model)
        tokens = enc.encode(text)
        return {"ok": True, "tokens": len(tokens), "model": model, "method": "tiktoken"}
    except Exception:
        pass
    # Fallback: ~4 chars per token
    import re as _re
    words = len(_re.split(r"\s+", (text or "").strip())) or 1
    chars = len(text or "")
    rough = max(int(chars / 4), words)
    return {"ok": True, "tokens": rough, "model": "estimate", "method": "rough (~4 chars/token)"}

def sympy_solve(expression: str, variable: str = "x", mode: str = "solve") -> dict:
    """
    Symbolic math via SymPy. mode options:
    - 'solve': solve equation for variable (e.g. "x**2 - 4", "x" → [-2, 2])
    - 'simplify': algebraically simplify an expression
    - 'diff': differentiate with respect to variable
    - 'integrate': integrate with respect to variable
    - 'expand': expand/distribute
    - 'factor': factor into irreducible parts
    - 'latex': render as LaTeX string
    - 'numeric': numerical evaluation (calls evalf)
    """
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import implicit_multiplication_application, parse_expr, standard_transformations
        transforms = standard_transformations + (implicit_multiplication_application,)
        local_dict = {v: sp.Symbol(v) for v in "xyzabcntk"}
        if variable not in local_dict:
            local_dict[variable] = sp.Symbol(variable)
        expr = parse_expr(expression, local_dict=local_dict, transformations=transforms)
        var = local_dict.get(variable, sp.Symbol(variable))
        if mode == "solve":
            sol = sp.solve(expr, var)
            return {"ok": True, "mode": "solve", "variable": variable, "solutions": [str(s) for s in sol]}
        elif mode == "diff":
            return {"ok": True, "mode": "diff", "result": str(sp.diff(expr, var)), "latex": sp.latex(sp.diff(expr, var))}
        elif mode == "integrate":
            return {"ok": True, "mode": "integrate", "result": str(sp.integrate(expr, var)), "latex": sp.latex(sp.integrate(expr, var))}
        elif mode == "simplify":
            return {"ok": True, "mode": "simplify", "result": str(sp.simplify(expr)), "latex": sp.latex(sp.simplify(expr))}
        elif mode == "expand":
            return {"ok": True, "mode": "expand", "result": str(sp.expand(expr))}
        elif mode == "factor":
            return {"ok": True, "mode": "factor", "result": str(sp.factor(expr))}
        elif mode == "latex":
            return {"ok": True, "mode": "latex", "latex": sp.latex(expr)}
        elif mode == "numeric":
            return {"ok": True, "mode": "numeric", "result": str(expr.evalf()), "float": float(expr.evalf())}
        else:
            return {"ok": False, "error": f"Unknown mode: {mode}. Use solve/diff/integrate/simplify/expand/factor/latex/numeric"}
    except ImportError:
        return {"ok": False, "error": "sympy not installed: pip install sympy"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def nlp_analyze(text: str, tasks: list | None = None) -> dict:
    """
    NLP analysis pipeline. tasks: list of ['entities', 'keywords', 'sentiment', 'sentences', 'pos']
    Default: all. Uses spaCy if available, falls back to NLTK + basic heuristics.
    """
    if not tasks:
        tasks = ["entities", "keywords", "sentiment", "sentences"]
    result: dict = {"ok": True, "text_length": len(text), "tasks": tasks}

    # Try spaCy first
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            # Model not downloaded — try blank
            nlp = spacy.blank("en")
        doc = nlp(text[:50000])
        if "entities" in tasks:
            result["entities"] = [
                {"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char}
                for ent in doc.ents
            ][:50]
        if "sentences" in tasks:
            result["sentences"] = [str(s)[:200] for s in list(doc.sents)[:20]]
        if "pos" in tasks:
            result["pos_tags"] = [
                {"token": t.text, "pos": t.pos_, "dep": t.dep_}
                for t in doc if not t.is_space
            ][:60]
    except ImportError:
        pass

    # Keywords via KeyBERT
    if "keywords" in tasks:
        try:
            from keybert import KeyBERT
            kw_model = KeyBERT()
            keywords = kw_model.extract_keywords(text[:10000], keyphrase_ngram_range=(1, 2), top_n=12)
            result["keywords"] = [{"phrase": kw, "score": round(score, 4)} for kw, score in keywords]
        except ImportError:
            # Fallback: simple frequency-based keywords
            import re
            words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
            freq: dict = {}
            for w in words:
                freq[w] = freq.get(w, 0) + 1
            stopwords = {"that", "this", "with", "from", "they", "have", "been", "were", "will", "would", "could", "should", "their", "there", "these", "those"}
            keywords_fb = sorted([(w, c) for w, c in freq.items() if w not in stopwords], key=lambda x: -x[1])[:12]
            result["keywords"] = [{"phrase": w, "score": c} for w, c in keywords_fb]

    # Basic sentiment (no ML needed — lexicon approach)
    if "sentiment" in tasks:
        try:
            from textblob import TextBlob
            tb = TextBlob(text[:5000])
            result["sentiment"] = {"polarity": round(tb.sentiment.polarity, 3), "subjectivity": round(tb.sentiment.subjectivity, 3)}
        except ImportError:
            # Very basic heuristic
            pos_words = {"good","great","excellent","amazing","love","wonderful","best","fantastic","perfect","brilliant"}
            neg_words = {"bad","terrible","awful","horrible","hate","worst","poor","disappointing","fail","wrong"}
            words_lower = set(text.lower().split())
            pos = len(words_lower & pos_words)
            neg = len(words_lower & neg_words)
            polarity = (pos - neg) / max(pos + neg, 1)
            result["sentiment"] = {"polarity": round(polarity, 3), "method": "lexicon_heuristic"}

    return result

def ocr_image(path: str, lang: str = "eng") -> dict:
    """
    Extract text from an image using OCR.
    Tries EasyOCR first (better accuracy, no Tesseract required),
    then falls back to pytesseract (requires Tesseract binary installed).
    lang: language code ('eng', 'fra', 'deu', 'jpn', 'chi_sim', etc.)
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    ext = target.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}:
        return {"ok": False, "error": f"Unsupported image format: {ext}"}

    # Try EasyOCR
    try:
        import easyocr
        lang_map = {"eng": "en", "fra": "fr", "deu": "de", "chi_sim": "ch_sim", "jpn": "ja"}
        easy_lang = lang_map.get(lang, "en")
        reader = easyocr.Reader([easy_lang], gpu=False, verbose=False)
        results = reader.readtext(str(target))
        text_parts = [item[1] for item in results if item[2] > 0.1]
        full_text = "\n".join(text_parts)
        return {
            "ok": True, "method": "easyocr", "path": str(target),
            "text": full_text[:8000], "blocks": len(results),
            "confidence_avg": round(sum(r[2] for r in results) / max(len(results), 1), 3),
        }
    except ImportError:
        pass

    # Fallback: pytesseract
    try:
        import pytesseract
        from PIL import Image as PILImage
        with PILImage.open(str(target)) as img:
            text = pytesseract.image_to_string(img, lang=lang)
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
        conf_avg = sum(confidences) / max(len(confidences), 1)
        return {
            "ok": True, "method": "pytesseract", "path": str(target),
            "text": text.strip()[:8000],
            "confidence_avg": round(conf_avg, 1),
        }
    except ImportError:
        return {"ok": False, "error": "OCR requires easyocr or pytesseract+Pillow: pip install easyocr OR pip install pytesseract Pillow"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def plot_chart(
    data: dict,
    chart_type: str = "bar",
    title: str = "",
    output_path: str = "",
    xlabel: str = "",
    ylabel: str = "",
) -> dict:
    """
    Generate a chart and save it as PNG. Returns path to saved file.
    chart_type: 'bar' | 'line' | 'scatter' | 'pie' | 'histogram' | 'heatmap'
    data format:
    - bar/line: {"labels": [...], "values": [...]} or {"Series A": [...], "Series B": [...], "labels": [...]}
    - scatter: {"x": [...], "y": [...]}
    - pie: {"labels": [...], "values": [...]}
    - histogram: {"values": [...], "bins": 20}
    - heatmap: {"matrix": [[...], ...], "row_labels": [...], "col_labels": [...]}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend, always safe
        import matplotlib.pyplot as plt
        import numpy as _np

        fig, ax = plt.subplots(figsize=(10, 6))
        if title:
            ax.set_title(title, fontsize=14, fontweight="bold")
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)

        if chart_type == "bar":
            labels = data.get("labels", list(range(len(data.get("values", [])))))
            values = data.get("values", [])
            ax.bar(range(len(labels)), values, tick_label=[str(lbl) for lbl in labels])
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "line":
            labels = data.get("labels", list(range(len(data.get("values", [])))))
            for key, vals in data.items():
                if key == "labels":
                    continue
                if isinstance(vals, (list, tuple)):
                    ax.plot(labels if len(labels) == len(vals) else range(len(vals)), vals, label=key, marker="o", markersize=3)
            ax.legend()

        elif chart_type == "scatter":
            x, y = data.get("x", []), data.get("y", [])
            labels = data.get("point_labels", [])
            ax.scatter(x, y, alpha=0.7)
            for i, label in enumerate(labels[:len(x)]):
                ax.annotate(str(label), (x[i], y[i]), fontsize=7)

        elif chart_type == "pie":
            labels = data.get("labels", [])
            values = data.get("values", [])
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=140)
            ax.axis("equal")

        elif chart_type == "histogram":
            values = data.get("values", [])
            bins = data.get("bins", 20)
            ax.hist(values, bins=bins, edgecolor="black", alpha=0.7)

        elif chart_type == "heatmap":
            matrix = data.get("matrix", [[]])
            row_labels = data.get("row_labels", [])
            col_labels = data.get("col_labels", [])
            arr = _np.array(matrix)
            im = ax.imshow(arr, cmap="viridis", aspect="auto")
            plt.colorbar(im, ax=ax)
            if row_labels:
                ax.set_yticks(range(len(row_labels)))
                ax.set_yticklabels(row_labels)
            if col_labels:
                ax.set_xticks(range(len(col_labels)))
                ax.set_xticklabels(col_labels, rotation=45, ha="right")
        else:
            plt.close(fig)
            return {"ok": False, "error": f"Unknown chart_type: {chart_type}"}

        # Determine save path
        if output_path:
            save_path = Path(output_path)
        else:
            import tempfile
            import time
            tmp_dir = Path(tempfile.gettempdir())
            save_path = tmp_dir / f"layla_chart_{int(time.time())}.png"

        plt.tight_layout()
        fig.savefig(str(save_path), dpi=120, bbox_inches="tight")
        plt.close(fig)
        return {"ok": True, "chart_type": chart_type, "path": str(save_path), "title": title}
    except ImportError:
        return {"ok": False, "error": "matplotlib not installed: pip install matplotlib"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def context_compress(text: str, target_tokens: int = 2000, strategy: str = "smart") -> dict:
    """
    Compress text to fit within a token budget.
    strategy:
    - 'smart': extract most important sentences (extractive summarization)
    - 'truncate': simple head truncation
    - 'middle_out': keep head + tail, drop middle (good for code files with imports + logic)
    Returns compressed text + token estimates before/after.
    """
    def rough_tokens(t: str) -> int:
        return max(int(len(t) / 4), len(t.split()))

    original_tokens = rough_tokens(text)

    if original_tokens <= target_tokens:
        return {"ok": True, "strategy": "no_compression_needed", "original_tokens": original_tokens,
                "compressed_tokens": original_tokens, "text": text, "ratio": 1.0}

    if strategy == "truncate":
        char_budget = target_tokens * 4
        compressed = text[:char_budget]
        return {"ok": True, "strategy": "truncate", "original_tokens": original_tokens,
                "compressed_tokens": rough_tokens(compressed), "text": compressed,
                "ratio": round(rough_tokens(compressed) / original_tokens, 3)}

    if strategy == "middle_out":
        char_budget = target_tokens * 4
        head = text[:char_budget // 2]
        tail = text[-(char_budget // 2):]
        compressed = head + "\n\n[... content compressed ...]\n\n" + tail
        return {"ok": True, "strategy": "middle_out", "original_tokens": original_tokens,
                "compressed_tokens": rough_tokens(compressed), "text": compressed,
                "ratio": round(rough_tokens(compressed) / original_tokens, 3)}

    # Smart: sentence scoring (position + length + keyword density)
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', text)
    if not sentences:
        sentences = text.split("\n")

    # Score each sentence
    total = len(sentences)
    def score_sentence(s: str, idx: int) -> float:
        pos_score = 1.5 if idx < total * 0.1 else (1.2 if idx > total * 0.9 else 1.0)
        len_score = 1.0 if 20 < len(s) < 200 else 0.6
        caps = len(_re.findall(r'\b[A-Z][a-z]+\b', s))
        return pos_score * len_score * (1 + caps * 0.1)

    scored = [(score_sentence(s, i), i, s) for i, s in enumerate(sentences)]
    scored.sort(key=lambda x: -x[0])

    # Greedily pick sentences until token budget
    picked_indices: set[int] = set()
    budget_used = 0
    for score, idx, sentence in scored:
        t = rough_tokens(sentence)
        if budget_used + t <= target_tokens:
            picked_indices.add(idx)
            budget_used += t
        if budget_used >= target_tokens:
            break

    # Reconstruct in original order
    compressed_parts = [sentences[i] for i in sorted(picked_indices)]
    compressed = " ".join(compressed_parts)
    return {"ok": True, "strategy": "smart", "original_tokens": original_tokens,
            "compressed_tokens": rough_tokens(compressed), "text": compressed,
            "ratio": round(rough_tokens(compressed) / original_tokens, 3)}

def describe_image(path: str, detail: str = "brief") -> dict:
    """
    Generate a natural language description of an image.
    detail: 'brief' | 'detailed'
    Uses BLIP (Salesforce/blip-image-captioning-base) via transformers.
    Falls back to metadata-only description if transformers not installed.
    Note: First call downloads ~500 MB model. Cached afterward.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    ext = target.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}:
        return {"ok": False, "error": f"Unsupported image format: {ext}"}

    # Try BLIP via transformers
    try:
        import torch
        from PIL import Image as PILImage
        from transformers import BlipForConditionalGeneration, BlipProcessor

        try:
            import runtime_safety

            _cfg = runtime_safety.load_config()
            model_name = (_cfg.get("image_model") or "Salesforce/blip-image-captioning-base").strip()
        except Exception:
            model_name = "Salesforce/blip-image-captioning-base"
        try:
            processor = BlipProcessor.from_pretrained(model_name)
            model = BlipForConditionalGeneration.from_pretrained(model_name)
        except Exception as e:
            return {"ok": False, "error": f"Failed to load BLIP model: {e}. Run: pip install transformers torch Pillow"}

        with PILImage.open(str(target)) as img:
            img_rgb = img.convert("RGB")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)

        if detail == "detailed":
            # Conditional captioning with a prompt
            text_prompt = "a photography of"
            inputs = processor(img_rgb, text_prompt, return_tensors="pt").to(device)
        else:
            inputs = processor(img_rgb, return_tensors="pt").to(device)

        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=80)
        caption = processor.decode(out[0], skip_special_tokens=True)

        # Also run OCR if text is likely present
        ocr_text = ""
        try:
            import easyocr
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            ocr_results = reader.readtext(str(target))
            ocr_text = " ".join([r[1] for r in ocr_results if r[2] > 0.3])[:500]
        except Exception:
            pass

        result: dict = {
            "ok": True, "path": str(target), "model": "BLIP",
            "caption": caption, "detail": detail,
        }
        if ocr_text:
            result["ocr_text"] = ocr_text
        return result

    except ImportError:
        # Fallback: return metadata + OCR if available
        result_fb: dict = {
            "ok": True, "path": str(target), "model": "fallback_metadata",
            "warning": "transformers not installed (pip install transformers torch) — BLIP captioning unavailable",
        }
        try:
            from PIL import Image as PILImage
            with PILImage.open(str(target)) as img:
                result_fb["size"] = f"{img.width}x{img.height}"
                result_fb["mode"] = img.mode
                result_fb["format"] = img.format
        except Exception:
            pass
        # Try OCR anyway
        try:
            import easyocr
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            ocr_results = reader.readtext(str(target))
            ocr_text = " ".join([r[1] for r in ocr_results if r[2] > 0.3])[:500]
            if ocr_text:
                result_fb["ocr_text"] = ocr_text
                result_fb["caption"] = f"Image contains text: {ocr_text[:200]}"
        except Exception:
            pass
        return result_fb
    except Exception as e:
        return {"ok": False, "error": str(e)}

def summarize_text(text: str, sentences: int = 5, method: str = "extractive") -> dict:
    """
    Summarize text. method:
    - 'extractive': score sentences by position, length, keyword density. No deps.
    - 'abstractive': uses transformers (facebook/bart-large-cnn). First run ~1.5 GB download.
    sentences: number of sentences to include (extractive) or target length hint (abstractive).
    """
    import re as _re

    if not text.strip():
        return {"ok": False, "error": "Empty text"}

    if method == "abstractive":
        try:
            from transformers import pipeline as _pipeline
            summarizer = _pipeline("summarization", model="facebook/bart-large-cnn")
            max_len = min(sentences * 40, 200)
            result_text = summarizer(text[:4096], max_length=max_len, min_length=30, do_sample=False)[0]["summary_text"]
            return {"ok": True, "method": "abstractive", "model": "bart-large-cnn", "summary": result_text, "original_chars": len(text)}
        except ImportError:
            pass  # Fall through to extractive

    # Extractive summarization (no deps)
    sentence_list = _re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentence_list:
        sentence_list = [s.strip() for s in text.split("\n") if s.strip()]

    if len(sentence_list) <= sentences:
        return {"ok": True, "method": "extractive", "summary": text, "sentences_in": len(sentence_list), "sentences_out": len(sentence_list)}

    words = _re.findall(r'\b\w{4,}\b', text.lower())
    freq: dict = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    max_freq = max(freq.values(), default=1)

    scored = []
    total = len(sentence_list)
    for i, sent in enumerate(sentence_list):
        pos = 1.5 if i < total * 0.15 else (1.2 if i > total * 0.85 else 1.0)
        sent_words = _re.findall(r'\b\w{4,}\b', sent.lower())
        tf_score = sum(freq.get(w, 0) / max_freq for w in sent_words) / max(len(sent_words), 1)
        len_score = 1.0 if 15 < len(sent.split()) < 50 else 0.7
        scored.append((pos * len_score * (1 + tf_score), i, sent))

    top = sorted(scored, key=lambda x: -x[0])[:sentences]
    summary = " ".join(s for _, _, s in sorted(top, key=lambda x: x[1]))
    return {"ok": True, "method": "extractive", "summary": summary, "sentences_in": total, "sentences_out": len(top), "original_chars": len(text)}

def classify_text(text: str, labels: list | None = None, threshold: float = 0.0) -> dict:
    """
    Classify text into one or more categories.
    labels: list of class names. If empty, uses general-purpose categories.
    Uses zero-shot classification via transformers if available,
    falls back to cosine similarity via sentence-transformers,
    falls back to keyword-frequency scoring.
    threshold: minimum score (0.0 = return all, 0.5 = return only confident)
    """
    if not labels:
        labels = ["technical", "creative", "analytical", "factual", "conversational", "instructional", "narrative"]

    # Try zero-shot with transformers
    try:
        from transformers import pipeline as _pipeline
        classifier = _pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
        result = classifier(text[:512], labels)
        scores = dict(zip(result["labels"], result["scores"]))
        filtered = {k: round(v, 4) for k, v in scores.items() if v >= threshold}
        return {"ok": True, "method": "zero-shot-transformers", "text_preview": text[:80], "scores": filtered, "top": result["labels"][0]}
    except (ImportError, Exception):
        pass

    # Fallback: sentence-transformers cosine similarity
    try:
        from sentence_transformers import SentenceTransformer
        from sentence_transformers import util as _stutil
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        text_emb = _model.encode(text[:512], convert_to_tensor=True)
        label_embs = _model.encode(labels, convert_to_tensor=True)
        scores_tensor = _stutil.cos_sim(text_emb, label_embs)[0]
        scores_dict = {label: round(float(score), 4) for label, score in zip(labels, scores_tensor)}
        filtered = {k: v for k, v in scores_dict.items() if v >= threshold}
        top = max(scores_dict, key=lambda x: scores_dict[x])
        return {"ok": True, "method": "sentence-transformers", "text_preview": text[:80], "scores": filtered, "top": top}
    except (ImportError, Exception):
        pass

    # Final fallback: keyword scoring
    text_lower = text.lower()
    keyword_map = {
        "technical": ["function","class","error","code","implement","system","algorithm","api","module"],
        "creative": ["imagine","story","describe","write","create","design","idea","dream","novel"],
        "analytical": ["analyze","compare","evaluate","assess","determine","examine","conclude","evidence"],
        "factual": ["according","reported","data","study","research","found","shows","indicates"],
        "conversational": ["you","i","we","me","your","my","hey","hi","think","feel","want"],
        "instructional": ["step","first","then","next","do","run","install","configure","how","guide"],
        "narrative": ["then","after","before","when","suddenly","finally","said","went","came"],
    }
    scores_fb = {}
    for label in labels:
        keywords = keyword_map.get(label, [label.lower()])
        hits = sum(1 for kw in keywords if kw in text_lower)
        scores_fb[label] = round(hits / max(len(keywords), 1), 4)
    total_s = sum(scores_fb.values()) or 1
    scores_norm = {k: round(v / total_s, 4) for k, v in scores_fb.items()}
    top = max(scores_norm, key=lambda x: scores_norm[x])
    return {"ok": True, "method": "keyword-fallback", "text_preview": text[:80], "scores": scores_norm, "top": top}

def translate_text(text: str, target_lang: str = "en", source_lang: str = "auto") -> dict:
    """
    Translate text. Uses deep-translator (Google backend) if installed.
    Falls back to LibreTranslate public API (rate-limited, no key required).
    target_lang: ISO 639-1 code (en, fr, de, es, zh, ja, ar, ru, pt, it, ko)
    source_lang: ISO 639-1 code or 'auto'
    """
    try:
        from deep_translator import GoogleTranslator
        src = source_lang if source_lang != "auto" else "auto"
        translator = GoogleTranslator(source=src, target=target_lang)
        chunks = [text[i:i+4999] for i in range(0, len(text), 4999)]
        translated_chunks = [translator.translate(chunk) for chunk in chunks]
        translated = " ".join(c for c in translated_chunks if c)
        return {"ok": True, "method": "google-translate", "source_lang": source_lang, "target_lang": target_lang, "translated": translated, "original_chars": len(text)}
    except ImportError:
        pass
    # Fallback: LibreTranslate public API
    try:
        import json as _json
        import urllib.request
        payload = _json.dumps({"q": text[:2000], "source": source_lang if source_lang != "auto" else "en", "target": target_lang, "format": "text"}).encode()
        req = urllib.request.Request(
            "https://libretranslate.com/translate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
            return {"ok": True, "method": "libretranslate-public", "source_lang": source_lang, "target_lang": target_lang, "translated": data.get("translatedText", ""), "original_chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": f"Translation requires deep-translator: pip install deep-translator. Error: {e}"}

def text_stats(text: str) -> dict:
    """
    Comprehensive text statistics and readability metrics.
    Returns: word/sentence/char counts, vocabulary richness, Flesch reading ease,
    avg sentence length, estimated reading time, top 15 non-stopword words.
    """
    import re as _re

    if not text.strip():
        return {"ok": False, "error": "Empty text"}

    words = _re.findall(r'\b[a-zA-Z]+\b', text)
    sentences = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    syllables = sum(max(1, len(_re.findall(r'[aeiouAEIOU]+', w))) for w in words)

    wc = len(words)
    sc = max(len(sentences), 1)
    unique = set(w.lower() for w in words)
    avg_wps = round(wc / sc, 1)
    avg_spw = round(syllables / max(wc, 1), 2)
    flesch = round(max(0.0, min(100.0, 206.835 - 1.015 * avg_wps - 84.6 * avg_spw)), 1)
    grade = "Easy" if flesch >= 70 else ("Standard" if flesch >= 50 else ("Difficult" if flesch >= 30 else "Very Difficult"))

    STOPWORDS = {"the","a","an","and","or","but","in","on","at","to","for","of","with","is","was","are","it","this","that","be","have","do","i","you","we","he","she","they","not","by","as","from","his","her","its","our","their","so","if","but","about","which"}
    freq: dict = {}
    for w in words:
        wl = w.lower()
        if wl not in STOPWORDS and len(wl) > 2:
            freq[wl] = freq.get(wl, 0) + 1

    return {
        "ok": True,
        "counts": {"words": wc, "unique_words": len(unique), "sentences": sc, "paragraphs": len(paragraphs), "characters": len(text)},
        "averages": {"words_per_sentence": avg_wps, "syllables_per_word": avg_spw},
        "readability": {"flesch_score": flesch, "grade": grade},
        "vocabulary_richness": round(len(unique) / max(wc, 1), 4),
        "reading_time_minutes": round(wc / 200, 1),
        "top_words": [{"word": w, "count": c} for w, c in sorted(freq.items(), key=lambda x: -x[1])[:15]],
    }

def embedding_generate(text: str | list, normalize: bool = True) -> dict:
    """
    Generate dense vector embeddings using Layla's RAG embedder (nomic-embed-text).
    text: string or list of strings.
    normalize: L2 normalize (default True — required for cosine similarity).
    Returns: embedding(s) as list of floats, dimension, model name.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.vector_store import _get_embedder
        embedder = _get_embedder()
        is_batch = isinstance(text, list)
        texts = text if is_batch else [text]
        embeddings = embedder.encode(texts, normalize_embeddings=normalize)
        emb_list = embeddings.tolist() if hasattr(embeddings, "tolist") else [list(e) for e in embeddings]
        return {"ok": True, "dimension": len(emb_list[0]) if emb_list else 0, "count": len(emb_list), "normalized": normalize, "embeddings": emb_list if is_batch else emb_list[0]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def extract_entities(text: str, entity_types: list | None = None) -> dict:
    """
    Extract named entities. entity_types: ['PERSON','ORG','GPE','DATE','MONEY',...]
    Uses spaCy if installed (en_core_web_sm); regex fallback for common patterns.
    """
    if not entity_types:
        entity_types = []
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(text[:50000])
            ents = [{"text": e.text, "label": e.label_, "start": e.start_char, "end": e.end_char} for e in doc.ents if not entity_types or e.label_ in entity_types]
            by_type: dict = {}
            for e in ents:
                by_type.setdefault(e["label"], []).append(e["text"])
            return {"ok": True, "method": "spacy", "total": len(ents), "by_type": by_type, "entities": ents[:100]}
        except OSError:
            pass
    except ImportError:
        pass
    import re as _re
    patterns = {"EMAIL": r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', "URL": r'https?://[^\s<>"\']+', "DATE": r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}', "MONEY": r'\$\d+(?:,\d{3})*(?:\.\d{2})?', "PHONE": r'\+?1?\s*\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}', "CAPITALIZED": r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'}
    ents = []
    for label, pattern in patterns.items():
        if entity_types and label not in entity_types:
            continue
        for m in _re.finditer(pattern, text):
            ents.append({"text": m.group(0), "label": label, "start": m.start(), "end": m.end()})
    by_type: dict = {}
    for e in ents:
        by_type.setdefault(e["label"], []).append(e["text"])
    return {"ok": True, "method": "regex-fallback", "total": len(ents), "by_type": by_type, "entities": ents[:100]}

def sentiment_timeline(texts: list, labels: list | None = None) -> dict:
    """
    Apply sentiment analysis to a list of texts. Returns per-item polarity + overall trend.
    Useful for review series, chat history, social media posts, time-series sentiment.
    """
    if not texts:
        return {"ok": False, "error": "Empty texts list"}

    def _score(t: str) -> float:
        try:
            from textblob import TextBlob
            return float(TextBlob(t[:2000]).sentiment.polarity)
        except ImportError:
            pos = {"good","great","excellent","love","best","fantastic","happy","positive","success","win","amazing","wonderful"}
            neg = {"bad","terrible","awful","hate","worst","poor","fail","wrong","negative","loss","sad","horrible","disaster"}
            words = set(t.lower().split())
            p, n = len(words & pos), len(words & neg)
            return (p - n) / max(p + n, 1)

    results = []
    for i, text in enumerate(texts[:100]):
        pol = round(_score(text), 4)
        lbl = labels[i] if labels and i < len(labels) else str(i)
        results.append({"label": lbl, "preview": text[:80], "polarity": pol, "sentiment": "positive" if pol > 0.1 else ("negative" if pol < -0.1 else "neutral")})

    scores = [r["polarity"] for r in results]
    avg = round(sum(scores) / len(scores), 4)
    trend = "stable"
    if len(scores) >= 4:
        mid = len(scores) // 2
        first_avg = sum(scores[:mid]) / mid
        second_avg = sum(scores[mid:]) / (len(scores) - mid)
        trend = "improving" if second_avg - first_avg > 0.05 else ("declining" if first_avg - second_avg > 0.05 else "stable")

    return {"ok": True, "count": len(results), "avg_polarity": avg, "trend": trend, "min": round(min(scores), 4), "max": round(max(scores), 4), "timeline": results}

def plot_scatter(x: list, y: list, labels: list | None = None, title: str = "", xlabel: str = "", ylabel: str = "", show_regression: bool = True, output_path: str = "") -> dict:
    """
    Scatter plot with optional linear regression line and RÂ² annotation.
    x, y: numeric lists. labels: optional point annotations. show_regression: draw best-fit line.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as _np
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(x, y, alpha=0.7, s=60, edgecolors="white", linewidth=0.5)
        if labels:
            for xi, yi, lbl in zip(x, y, labels):
                ax.annotate(str(lbl), (xi, yi), fontsize=7, alpha=0.8, xytext=(4, 4), textcoords="offset points")
        if show_regression and len(x) >= 3:
            xa, ya = _np.array(x, dtype=float), _np.array(y, dtype=float)
            m, b = _np.polyfit(xa, ya, 1)
            xl = _np.linspace(xa.min(), xa.max(), 100)
            ax.plot(xl, m*xl+b, "r--", alpha=0.7, linewidth=1.5)
            corr = _np.corrcoef(xa, ya)[0, 1]
            ax.annotate(f"RÂ²={corr**2:.4f}  y={m:.3f}x+{b:.3f}", xy=(0.05, 0.95), xycoords="axes fraction", fontsize=9, color="red")
        ax.set_title(title or "Scatter Plot", fontsize=13)
        ax.set_xlabel(xlabel or "x")
        ax.set_ylabel(ylabel or "y")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        import tempfile as _tmp
        import time as _time
        out = output_path or str(Path(_tmp.gettempdir()) / f"layla_scatter_{int(_time.time())}.png")
        fig.savefig(out, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return {"ok": True, "chart_type": "scatter", "path": out, "points": len(x), "regression": show_regression}
    except ImportError:
        return {"ok": False, "error": "matplotlib not installed: pip install matplotlib"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def plot_histogram(data: list, bins: int = 20, title: str = "", xlabel: str = "", show_kde: bool = True, output_path: str = "") -> dict:
    """
    Histogram with optional KDE (kernel density) overlay and descriptive stats annotation.
    data: numeric list. bins: number of histogram bins. show_kde: overlay smooth density curve.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as _np
        arr = _np.array(data, dtype=float)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.hist(arr, bins=bins, edgecolor="black", alpha=0.7, density=show_kde, color="#4C72B0")
        if show_kde:
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(arr)
                xr = _np.linspace(arr.min(), arr.max(), 200)
                ax.plot(xr, kde(xr), "r-", linewidth=2, label="KDE")
                ax.legend(fontsize=9)
            except ImportError:
                pass
        stats_txt = f"n={len(arr):,}  mean={arr.mean():.3f}  std={arr.std():.3f}  median={_np.median(arr):.3f}"
        ax.set_title(f"{title}\n{stats_txt}" if title else stats_txt, fontsize=11)
        ax.set_xlabel(xlabel or "value")
        ax.set_ylabel("density" if show_kde else "frequency")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        import tempfile as _tmp
        import time as _time
        out = output_path or str(Path(_tmp.gettempdir()) / f"layla_hist_{int(_time.time())}.png")
        fig.savefig(out, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return {"ok": True, "chart_type": "histogram", "path": out, "n": len(arr), "mean": round(float(arr.mean()), 4), "std": round(float(arr.std()), 4)}
    except ImportError:
        return {"ok": False, "error": "matplotlib not installed: pip install matplotlib"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_chain_plan(goal: str, context: str = "") -> dict:
    """
    Plan a multi-step tool execution sequence for a given goal using intent detection.
    Returns an ordered list of tools with purpose descriptions.
    This is a heuristic planner â€” the LLM adapts and executes the plan.
    """
    goal_lower = (goal + " " + context).lower()
    INTENT_PLANS = {
        "research": (["research","find","what is","who is","explain","look up"], [
            {"step": 1, "tool": "ddg_search", "purpose": "Broad web search"},
            {"step": 2, "tool": "wiki_search", "purpose": "Encyclopedic context"},
            {"step": 3, "tool": "arxiv_search", "purpose": "Academic papers if relevant"},
            {"step": 4, "tool": "fetch_article", "purpose": "Extract full article from best result"},
            {"step": 5, "tool": "summarize_text", "purpose": "Distill findings"},
            {"step": 6, "tool": "save_note", "purpose": "Store to memory"},
        ]),
        "code": (["code","analyze","review","bug","refactor","function","class","import","ast"], [
            {"step": 1, "tool": "workspace_map", "purpose": "Map project structure"},
            {"step": 2, "tool": "code_symbols", "purpose": "Index all symbols"},
            {"step": 3, "tool": "dependency_graph", "purpose": "Map imports"},
            {"step": 4, "tool": "code_metrics", "purpose": "Measure complexity"},
            {"step": 5, "tool": "find_todos", "purpose": "Identify outstanding issues"},
            {"step": 6, "tool": "code_lint", "purpose": "Check for violations"},
            {"step": 7, "tool": "security_scan", "purpose": "Security audit"},
        ]),
        "data": (["dataset","csv","excel","data","statistics","correlations","cluster","analyze data"], [
            {"step": 1, "tool": "dataset_summary", "purpose": "Full statistical overview"},
            {"step": 2, "tool": "plot_histogram", "purpose": "Distribution visualization"},
            {"step": 3, "tool": "cluster_data", "purpose": "Natural groupings"},
            {"step": 4, "tool": "scipy_compute", "purpose": "Statistical tests"},
            {"step": 5, "tool": "plot_scatter", "purpose": "Correlation exploration"},
            {"step": 6, "tool": "save_note", "purpose": "Record findings"},
        ]),
        "web_crawl": (["crawl","scrape","website","all pages","download docs","site"], [
            {"step": 1, "tool": "check_url", "purpose": "Verify accessibility"},
            {"step": 2, "tool": "extract_links", "purpose": "Map site structure"},
            {"step": 3, "tool": "crawl_site", "purpose": "Crawl + extract all pages"},
            {"step": 4, "tool": "vector_store", "purpose": "Index into RAG"},
        ]),
        "database": (["database","sql","query","schema","table"], [
            {"step": 1, "tool": "schema_introspect", "purpose": "Understand structure"},
            {"step": 2, "tool": "generate_sql", "purpose": "Draft SQL query"},
            {"step": 3, "tool": "sql_query", "purpose": "Execute and retrieve data"},
            {"step": 4, "tool": "dataset_summary", "purpose": "Analyze results"},
        ]),
        "image": (["image","photo","picture","ocr","caption","detect"], [
            {"step": 1, "tool": "ocr_image", "purpose": "Extract text"},
            {"step": 2, "tool": "describe_image", "purpose": "Generate caption"},
            {"step": 3, "tool": "detect_objects", "purpose": "Identify objects"},
        ]),
        "security": (["security","vulnerability","secret","scan","cve","bandit"], [
            {"step": 1, "tool": "security_scan", "purpose": "Static analysis (bandit)"},
            {"step": 2, "tool": "security_scan", "purpose": "Secret detection", "args": {"scan_type": "secrets"}},
            {"step": 3, "tool": "security_scan", "purpose": "Dependency audit", "args": {"scan_type": "deps"}},
            {"step": 4, "tool": "find_todos", "purpose": "Find security-related TODOs"},
        ]),
    }
    best_intent, best_score, best_plan = "research", 0, []
    for intent, (patterns, plan) in INTENT_PLANS.items():
        score = sum(1 for p in patterns if p in goal_lower)
        if score > best_score:
            best_score, best_intent, best_plan = score, intent, plan
    if not best_plan:
        best_plan = [{"step": 1, "tool": "tool_recommend", "purpose": "Find best tools"}, {"step": 2, "tool": "ddg_search", "purpose": "Gather information"}, {"step": 3, "tool": "save_note", "purpose": "Store findings"}]
    valid_plan = [s for s in best_plan if s["tool"] in TOOLS]
    return {"ok": True, "goal": goal, "detected_intent": best_intent, "plan": valid_plan, "step_count": len(valid_plan), "note": "Heuristic plan â€” LLM will adapt based on results at each step"}

