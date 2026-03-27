const fs = require('fs');
const path = require('path');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const fileNodes = input.fileNodes;
const importEdges = input.importEdges;

const directoryGroups = {};
fileNodes.forEach(node => {
  const parts = node.filePath.split(/[/\\]/);
  const group = parts.length > 1 ? parts[0] : 'root';
  if (!directoryGroups[group]) directoryGroups[group] = [];
  directoryGroups[group].push(node.id);
});

const interGroupImports = [];
const groupMap = {};
Object.entries(directoryGroups).forEach(([group, ids]) => {
  ids.forEach(id => groupMap[id] = group);
});

const pairCounts = {};
importEdges.forEach(edge => {
  const fromGroup = groupMap[edge.source];
  const toGroup = groupMap[edge.target];
  if (fromGroup && toGroup && fromGroup !== toGroup) {
    const key = `${fromGroup}->${toGroup}`;
    pairCounts[key] = (pairCounts[key] || 0) + 1;
  }
});

Object.entries(pairCounts).forEach(([pair, count]) => {
  const [from, to] = pair.split('->');
  interGroupImports.push({ from, to, count });
});

const patternMatches = {};
const patterns = {
  'scraper_agents': 'service',
  'scraper_agents/agents': 'service',
  'scraper_agents/extractors': 'utility',
  'scraper_agents/prompts': 'config',
  'root': 'api' // main.py, campaign.py etc are routers
};

Object.keys(directoryGroups).forEach(group => {
  patternMatches[group] = patterns[group] || 'other';
});

// Refine pattern matches by inspecting files in root
directoryGroups['root'].forEach(id => {
    if (id.includes('models.py')) patternMatches['models'] = 'data';
    if (id.includes('utils.py')) patternMatches['utils'] = 'utility';
});

const result = {
  scriptCompleted: true,
  directoryGroups,
  interGroupImports,
  patternMatches,
  fileStats: {
    totalFileNodes: fileNodes.length,
    filesPerGroup: Object.fromEntries(Object.entries(directoryGroups).map(([k, v]) => [k, v.length]))
  }
};

fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
console.log('Architecture structural analysis completed.');
