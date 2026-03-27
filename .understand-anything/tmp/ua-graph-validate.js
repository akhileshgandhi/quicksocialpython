const fs = require('fs');

const graphPath = process.argv[2];
const outputPath = process.argv[3];

const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const nodes = graph.nodes;
const edges = graph.edges;
const layers = graph.layers;
const tour = graph.tour;

const issues = [];
const warnings = [];
const nodeIds = new Set(nodes.map(n => n.id));

// Check duplicates
const seenIds = new Set();
nodes.forEach(n => {
  if (seenIds.has(n.id)) issues.push(`Duplicate node ID: ${n.id}`);
  seenIds.add(n.id);
});

// Referential integrity
edges.forEach((e, idx) => {
  if (!nodeIds.has(e.source)) issues.push(`Edge ${idx} source missing: ${e.source}`);
  if (!nodeIds.has(e.target)) issues.push(`Edge ${idx} target missing: ${e.target}`);
});

layers.forEach(l => {
  l.nodeIds.forEach(id => {
    if (!nodeIds.has(id)) issues.push(`Layer ${l.id} nodeIds missing: ${id}`);
  });
});

tour.forEach(s => {
  s.nodeIds.forEach(id => {
    if (!nodeIds.has(id)) issues.push(`Tour step ${s.order} nodeIds missing: ${id}`);
  });
});

// Layer coverage
const fileNodes = nodes.filter(n => n.type === 'file');
const coveredFiles = new Set();
layers.forEach(l => {
  l.nodeIds.forEach(id => {
    const node = nodes.find(n => n.id === id);
    if (node && node.type === 'file') coveredFiles.add(id);
  });
});

fileNodes.forEach(fn => {
  if (!coveredFiles.has(fn.id)) issues.push(`File node missing from layers: ${fn.id}`);
});

// Stats
const nodeTypes = {};
nodes.forEach(n => nodeTypes[n.type] = (nodeTypes[n.type] || 0) + 1);
const edgeTypes = {};
edges.forEach(e => edgeTypes[e.type] = (edgeTypes[e.type] || 0) + 1);

const result = {
  scriptCompleted: true,
  issues,
  warnings,
  stats: {
    totalNodes: nodes.length,
    totalEdges: edges.length,
    totalLayers: layers.length,
    tourSteps: tour.length,
    nodeTypes,
    edgeTypes
  }
};

fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
console.log('Graph validation completed.');
