import json
import os

def create_node(f, results_item):
    path = results_item['path']
    # Heuristic for summary
    summary = f"Source file for {path}."
    if 'main.py' in path:
        summary = "Entry point for the FastAPI application, configuring routers and static file hosting."
    elif 'campaign.py' in path:
        summary = "Handles AI-driven marketing campaign generation, orchestrating post creation and storage."
    elif 'models.py' in path:
        summary = "Defines the Pydantic data models and Enums for the system's data contracts."
    elif 'utils.py' in path:
        summary = "General purpose utility functions for image processing, Gemini interactions, and I/O."
    elif 'scraper_agents' in path:
        summary = f"Specialized agent or extractor for {path} within the scraping pipeline."

    tags = ["source"]
    if 'agents' in path: tags.append("agent")
    if 'extractors' in path: tags.append("extractor")
    if 'prompts' in path: tags.append("prompt-template")
    if results_item['metrics']['classCount'] > 0: tags.append("data-model")
    if 'main' in path or 'orchestrator' in path: tags.append("entry-point")

    complexity = "simple"
    if results_item['totalLines'] > 200: complexity = "moderate"
    if results_item['totalLines'] > 800: complexity = "complex"

    return {
        "id": f"file:{path}",
        "type": "file",
        "name": os.path.basename(path),
        "filePath": path,
        "summary": summary,
        "tags": tags,
        "complexity": complexity
    }

def process_batch(batch_files, all_results, batch_index):
    nodes = []
    edges = []
    
    file_ids = {}
    for r in all_results:
        file_ids[r['path']] = f"file:{r['path']}"

    for path in batch_files:
        res = next((r for r in all_results if r['path'] == path), None)
        if not res: continue
        
        # File node
        fn = create_node(path, res)
        nodes.append(fn)
        
        # Function nodes
        for func in res['functions']:
            if func['endLine'] - func['startLine'] >= 10:
                func_id = f"function:{path}:{func['name']}"
                nodes.append({
                    "id": func_id,
                    "type": "function",
                    "name": func['name'],
                    "filePath": path,
                    "lineRange": [func['startLine'], func['endLine']],
                    "summary": f"Function {func['name']} in {path}.",
                    "tags": ["function"],
                    "complexity": "simple"
                })
                edges.append({
                    "source": fn['id'],
                    "target": func_id,
                    "type": "contains",
                    "direction": "forward",
                    "weight": 1.0
                })
        
        # Class nodes
        for cls in res['classes']:
            cls_id = f"class:{path}:{cls['name']}"
            nodes.append({
                "id": cls_id,
                "type": "class",
                "name": cls['name'],
                "filePath": path,
                "lineRange": [cls['startLine'], cls['endLine']],
                "summary": f"Class {cls['name']} in {path}.",
                "tags": ["class"],
                "complexity": "simple"
            })
            edges.append({
                "source": fn['id'],
                "target": cls_id,
                "type": "contains",
                "direction": "forward",
                "weight": 1.0
            })
            
        # Import edges
        for imp in res['imports']:
            if imp['resolvedPath'] and not imp['isExternal']:
                edges.append({
                    "source": fn['id'],
                    "target": f"file:{imp['resolvedPath']}",
                    "type": "imports",
                    "direction": "forward",
                    "weight": 0.7
                })

    with open(f'.understand-anything/intermediate/batch-{batch_index}.json', 'w') as f:
        json.dump({"nodes": nodes, "edges": edges}, f, indent=2)

def main():
    with open('.understand-anything/tmp/ua-file-extract-results-all.json', 'r') as f:
        all_results = json.load(f)['results']
    
    all_paths = [r['path'] for r in all_results]
    
    batch_size = 5
    for i in range(0, len(all_paths), batch_size):
        batch = all_paths[i:i+batch_size]
        process_batch(batch, all_results, i // batch_size)

if __name__ == "__main__":
    main()
