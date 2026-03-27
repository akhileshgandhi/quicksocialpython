const fs = require('fs');
const path = require('path');

const inputPath = process.argv[2];
const outputPath = process.argv[3];

const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const nodes = input.nodes;
const edges = input.edges;

const fanIn = {};
const fanOut = {};
edges.forEach(e => {
  fanOut[e.source] = (fanOut[e.source] || 0) + 1;
  fanIn[e.target] = (fanIn[e.target] || 0) + 1;
});

const entryPointCandidates = nodes.filter(n => n.type === 'file').map(n => {
  let score = 0;
  if (['main.py', 'app.py', 'run.py'].includes(n.name)) score += 3;
  if (n.tags.includes('entry-point')) score += 2;
  if (!n.filePath.includes('/')) score += 1;
  return { id: n.id, score, name: n.name, summary: n.summary };
}).sort((a, b) => b.score - a.score);

const startNode = entryPointCandidates[0].id;
const queue = [startNode];
const visited = new Set([startNode]);
const order = [];
const depthMap = { [startNode]: 0 };
const byDepth = { 0: [startNode] };

let i = 0;
while (i < queue.length && queue.length < 50) {
  const current = queue[i++];
  order.push(current);
  const currentDepth = depthMap[current];
  
  edges.filter(e => e.source === current).forEach(e => {
    if (!visited.has(e.target)) {
      visited.add(e.target);
      queue.push(e.target);
      depthMap[e.target] = currentDepth + 1;
      if (!byDepth[currentDepth + 1]) byDepth[currentDepth + 1] = [];
      byDepth[currentDepth + 1].push(e.target);
    }
  });
}

const nodeSummaryIndex = {};
nodes.forEach(n => {
  nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary, tags: n.tags || [] };
});

const result = {
  scriptCompleted: true,
  entryPointCandidates: entryPointCandidates.slice(0, 5),
  fanInRanking: Object.entries(fanIn).sort((a, b) => b[1] - a[1]).slice(0, 20).map(x => ({id: x[0], fanIn: x[1]})),
  bfsTraversal: { startNode, order, depthMap, byDepth },
  nodeSummaryIndex,
  totalNodes: nodes.length
};

fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
console.log('Tour topology analysis completed.');
