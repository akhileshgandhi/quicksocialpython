import os
import sys
import json
import ast
import re

def analyze_python_file(file_path, project_root, all_files):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.splitlines()
    except Exception as e:
        return None

    tree = ast.parse(content)
    
    functions = []
    classes = []
    imports = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                "name": node.name,
                "startLine": node.lineno,
                "endLine": node.end_lineno,
                "params": [arg.arg for arg in node.args.args]
            })
        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "startLine": node.lineno,
                "endLine": node.end_lineno,
                "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)],
                "properties": [] # Simplified
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "source": alias.name,
                    "resolvedPath": None,
                    "specifiers": [alias.name],
                    "line": node.lineno,
                    "isExternal": True
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            is_external = True
            resolved = None
            
            if level > 0:
                is_external = False
                # Local relative import
                current_dir = os.path.dirname(file_path)
                parts = module.split('.')
                for _ in range(level - 1):
                    current_dir = os.path.dirname(current_dir)
                
                potential = os.path.join(current_dir, *parts)
                # Try .py or /__init__.py
                for ext in ['.py', '/__init__.py']:
                    check = (potential + ext).replace('\\', '/')
                    rel_check = os.path.relpath(check, project_root).replace('\\', '/')
                    if rel_check in all_files:
                        resolved = rel_check
                        break
            else:
                # Potential local absolute import or external
                parts = module.split('.')
                potential = os.path.join(project_root, *parts)
                for ext in ['.py', '/__init__.py']:
                    check = (potential + ext).replace('\\', '/')
                    rel_check = os.path.relpath(check, project_root).replace('\\', '/')
                    if rel_check in all_files:
                        resolved = rel_check
                        is_external = False
                        break
            
            imports.append({
                "source": module,
                "resolvedPath": resolved,
                "specifiers": [alias.name for alias in node.names],
                "line": node.lineno,
                "isExternal": is_external
            })

    return {
        "path": os.path.relpath(file_path, project_root).replace('\\', '/'),
        "language": "python",
        "totalLines": len(lines),
        "nonEmptyLines": len([l for l in lines if l.strip()]),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "exports": [], # Python doesn't have explicit exports in the same way, but top-level names are exports.
        "metrics": {
            "importCount": len(imports),
            "exportCount": 0,
            "functionCount": len(functions),
            "classCount": len(classes)
        }
    }

def main():
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    project_root = data['projectRoot']
    all_files = set(data['allProjectFiles'])
    batch_files = data['batchFiles']
    
    results = []
    skipped = []
    
    for bf in batch_files:
        full_path = os.path.join(project_root, bf['path'])
        res = analyze_python_file(full_path, project_root, all_files)
        if res:
            results.append(res)
        else:
            skipped.append(bf['path'])
            
    output = {
        "scriptCompleted": True,
        "filesAnalyzed": len(results),
        "filesSkipped": skipped,
        "results": results
    }
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    main()
