"""
Polish subtitle JSON files (one segment at a time, or all at once) using AI.

Difference from polish_transcription.py:
- That one polishes the full project transcription (input.json) BEFORE cutting.
- This one polishes each per-cut JSON in subs/ (post-cut), so the user can
  trigger correction on demand for individual viral segments from the WebUI.

The AI sees only the text of one segment's transcript at a time — a focused
context window produces fewer hallucinations than re-running over the whole
video. The original timestamps and word-level alignment are preserved when
the word count matches before/after correction.
"""
import json
import os

from scripts.polish_transcription import (
    build_prompt,
    call_gemini_simple,
    parse_corrections,
    apply_corrections_to_data,
)


def polish_json_file(json_path, api_key, model_name="gemini-3.5-flash", backup=True):
    """
    Polish a single subtitle JSON file in place using the configured AI.

    Args:
        json_path: Absolute path to the *_processed.json file (subs/ folder).
        api_key: Gemini API key.
        model_name: Gemini model to use.
        backup: If True, save a backup as *.original.json next to the file
                (only the first time — preserves the very first version).

    Returns:
        dict: { "success": bool, "applied": int, "total": int, "error": str|None }
    """
    if not os.path.exists(json_path):
        return {"success": False, "applied": 0, "total": 0, "error": f"File not found: {json_path}"}

    if not api_key:
        return {"success": False, "applied": 0, "total": 0, "error": "Missing API key."}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"success": False, "applied": 0, "total": 0, "error": f"Failed to load JSON: {e}"}

    segments = data.get("segments", [])
    if not segments:
        return {"success": False, "applied": 0, "total": 0, "error": "No segments in JSON."}

    # Backup (only first time, to keep the *original* — not the previous polish)
    if backup:
        backup_path = json_path.replace(".json", ".original.json")
        if not os.path.exists(backup_path):
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception as e:
                # Non-fatal: just log
                print(f"[PolishSegment] Warning: could not backup {backup_path}: {e}")

    # Build prompt and call AI for the whole segment list at once.
    # A single cut typically has <50 lines, well under any chunk limit.
    texts = [seg.get("text", "").strip() for seg in segments]
    prompt = build_prompt(texts)

    response_text = call_gemini_simple(prompt, api_key, model_name=model_name)
    if not response_text:
        return {"success": False, "applied": 0, "total": len(segments), "error": "AI returned empty response."}

    corrections = parse_corrections(response_text, len(texts))
    if corrections is None:
        return {
            "success": False,
            "applied": 0,
            "total": len(segments),
            "error": f"AI response line count mismatch (expected {len(texts)}).",
        }

    applied = apply_corrections_to_data(data, corrections)

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        return {"success": False, "applied": applied, "total": len(segments), "error": f"Failed to save: {e}"}

    return {"success": True, "applied": applied, "total": len(segments), "error": None}


def find_segment_json(project_folder, segment_index):
    """
    Find the subs/*_processed.json file for a given segment index.

    Filenames follow the pattern '<index:03d>_<safe_title>_processed.json'
    (created by cut_segments.py) or 'final-output<index:03d>_processed.json'
    (legacy). Returns absolute path or None.
    """
    subs_dir = os.path.join(project_folder, "subs")
    if not os.path.isdir(subs_dir):
        return None

    idx_str = f"{int(segment_index):03d}"
    candidates = []
    for fname in os.listdir(subs_dir):
        if not fname.endswith("_processed.json"):
            continue
        if fname.startswith(f"{idx_str}_") or f"output{idx_str}" in fname:
            candidates.append(os.path.join(subs_dir, fname))

    # Prefer the title-based name (cut_segments style) over legacy
    candidates.sort(key=lambda p: ("output" in os.path.basename(p), p))
    return candidates[0] if candidates else None


def list_segment_jsons(project_folder):
    """Return absolute paths of all *_processed.json files in subs/, sorted by index."""
    subs_dir = os.path.join(project_folder, "subs")
    if not os.path.isdir(subs_dir):
        return []
    files = [
        os.path.join(subs_dir, f)
        for f in os.listdir(subs_dir)
        if f.endswith("_processed.json")
    ]
    files.sort()
    return files
