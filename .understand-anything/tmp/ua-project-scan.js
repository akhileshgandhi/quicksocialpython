const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const projectRoot = process.argv[2];
const outputPath = process.argv[3];

if (!projectRoot || !outputPath) {
  console.error('Usage: node ua-project-scan.js <project-root> <output-path>');
  process.exit(1);
}

function getTrackedFiles(root) {
  try {
    const output = execSync('git ls-files', { cwd: root, encoding: 'utf8' });
    return output.split('\n').filter(f => f.trim() !== '');
  } catch (e) {
    return walk(root);
  }
}

function walk(dir, base = '') {
  let results = [];
  const list = fs.readdirSync(dir);
  list.forEach(file => {
    const fullPath = path.join(dir, file);
    const relPath = path.join(base, file);
    const stat = fs.statSync(fullPath);
    if (stat && stat.isDirectory()) {
      results = results.concat(walk(fullPath, relPath));
    } else {
      results.push(relPath.replace(/\\/g, '/'));
    }
  });
  return results;
}

const excludePatterns = [
  'node_modules/', '.git/', 'vendor/', 'venv/', '.venv/', '__pycache__/',
  'dist/', 'build/', 'out/', 'coverage/', '.next/', '.cache/', '.turbo/', 'target/',
  '.idea/', '.vscode/',
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.pdf', '.zip', '.tar', '.gz',
  '.min.js', '.min.css', '.map', '.d.ts', '.generated.',
  '.md', '.txt', '.yml', '.yaml', '.toml', '.json', '.xml', '.lock', '.cfg', '.ini', 'Makefile', 'Dockerfile',
  'LICENSE', '.gitignore', '.editorconfig', '.prettierrc', '.eslintrc', '.log'
];

const extensionToLang = {
  '.ts': 'typescript', '.tsx': 'typescript',
  '.js': 'javascript', '.jsx': 'javascript',
  '.py': 'python',
  '.go': 'go',
  '.rs': 'rust',
  '.java': 'java',
  '.rb': 'ruby',
  '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.h': 'cpp', '.hpp': 'cpp',
  '.c': 'c',
  '.cs': 'csharp',
  '.swift': 'swift',
  '.kt': 'kotlin',
  '.php': 'php',
  '.vue': 'vue',
  '.svelte': 'svelte',
  '.sh': 'bash', '.bash': 'bash'
};

const allFiles = getTrackedFiles(projectRoot);
const sourceFiles = allFiles.filter(f => {
  const isExcluded = excludePatterns.some(p => f.includes(p) || f.endsWith(p.replace('/', '')));
  if (isExcluded) return false;
  const ext = path.extname(f);
  return !!extensionToLang[ext];
}).map(f => {
  const fullPath = path.join(projectRoot, f);
  let sizeLines = 0;
  try {
    const content = fs.readFileSync(fullPath, 'utf8');
    sizeLines = content.split('\n').length;
  } catch (e) {}
  return {
    path: f,
    language: extensionToLang[path.extname(f)],
    sizeLines
  };
}).sort((a, b) => a.path.localeCompare(b.path));

const languages = Array.from(new Set(sourceFiles.map(f => f.language))).sort();

// Framework Detection
const frameworks = [];
const reqPath = path.join(projectRoot, 'requirements.txt');
if (fs.existsSync(reqPath)) {
  const reqs = fs.readFileSync(reqPath, 'utf8').toLowerCase();
  const known = ['fastapi', 'django', 'flask', 'pydantic', 'uvicorn', 'aiohttp', 'playwright', 'beautifulsoup4', 'opencv', 'numpy', 'pillow'];
  known.forEach(k => {
    if (reqs.includes(k)) frameworks.push(k.charAt(0).toUpperCase() + k.slice(1));
  });
}

const complexity = sourceFiles.length <= 20 ? 'small' : sourceFiles.length <= 100 ? 'moderate' : sourceFiles.length <= 500 ? 'large' : 'very-large';

const name = path.basename(projectRoot);

const result = {
  scriptCompleted: true,
  name,
  rawDescription: "",
  readmeHead: "",
  languages,
  frameworks,
  files: sourceFiles,
  totalFiles: sourceFiles.length,
  estimatedComplexity: complexity
};

// Try to get description from main.py if possible
const mainPath = path.join(projectRoot, 'main.py');
if (fs.existsSync(mainPath)) {
  const mainContent = fs.readFileSync(mainPath, 'utf8');
  const match = mainContent.match(/description\s*=\s*["']([^"']+)["']/);
  if (match) result.rawDescription = match[1];
}

const readmePath = path.join(projectRoot, 'AGENTIC_PIPELINE_PLAN.md');
if (fs.existsSync(readmePath)) {
    result.readmeHead = fs.readFileSync(readmePath, 'utf8').split('\n').slice(0, 10).join('\n');
}

fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
console.log('Project scan completed.');
