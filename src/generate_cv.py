import argparse
import logging
import json
import warnings
from pathlib import Path
from cv_generator_graph import build_graph
from pdf_generator import generate_pdf

# Suppress annoying logging from httpx if possible
logging.getLogger("httpx").setLevel(logging.WARNING)

def main():
    parser = argparse.ArgumentParser(description="Agentic CV Generator via LangGraph")
    parser.add_argument("--jd", required=True, help="Path to the Job Description text file")
    parser.add_argument("--out", default="ai-generated-cvs/Target_CV.md", help="Output path for the Markdown CV")
    parser.add_argument("--wiki-dir", help="Path to the llm-wiki folder (defaults to LLM_WIKI_DIR env var or 'llm-wiki')")
    args = parser.parse_args()

    import os
    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    jd_path = Path(args.jd)
    if not jd_path.exists():
        print(f"❌ Error: Job Description file not found at {jd_path}")
        return
        
    with open(jd_path, "r", encoding="utf-8") as f:
        jd_content = f.read()

    print(f"🚀 Initializing LangGraph CV Generator Pipeline against `{jd_path.name}`...")
    app = build_graph()
    
    initial_state = {
        "job_description": jd_content,
        "iteration_count": 0
    }
    
    print("⏳ Running pipeline using configured models. This may take a few minutes...\n")
    final_state = app.invoke(initial_state)
    
    draft = final_state.get("draft_cv", "")
    pdf_template = final_state.get("pdf_template", "templates/base.css")
    
    # Save Markdown Output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(draft)
        
    # Save Context (Graph State) for debugging
    context_path = out_path.with_name(f"{out_path.stem}_context.json")
    state_to_save = {k: v for k, v in final_state.items() if k != "draft_cv"}
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(state_to_save, f, indent=2)
        
    print(f"\n✅ Build complete! Markdown saved to {out_path}")
    print(f"📦 Context/State backed up to {context_path}")
    print(f"🔄 Audit iterations required: {final_state.get('iteration_count')}")

if __name__ == "__main__":
    main()
