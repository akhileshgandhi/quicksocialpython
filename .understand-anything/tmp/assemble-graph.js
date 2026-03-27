const fs = require('fs');

const scanResult = JSON.parse(fs.readFileSync('.understand-anything/intermediate/scan-result.json', 'utf8'));
const batchAll = JSON.parse(fs.readFileSync('.understand-anything/intermediate/batch-all.json', 'utf8'));
const layers = JSON.parse(fs.readFileSync('.understand-anything/intermediate/layers.json', 'utf8'));
const tour = JSON.parse(fs.readFileSync('.understand-anything/intermediate/tour.json', 'utf8'));

const finalGraph = {
  metadata: {
    name: scanResult.name,
    description: scanResult.description,
    languages: scanResult.languages,
    frameworks: scanResult.frameworks,
    totalFiles: scanResult.totalFiles,
    estimatedComplexity: scanResult.estimatedComplexity
  },
  nodes: batchAll.nodes,
  edges: batchAll.edges,
  layers: layers,
  tour: tour
};

fs.writeFileSync('.understand-anything/knowledge-graph.json', JSON.stringify(finalGraph, null, 2));
console.log('Final knowledge graph assembled.');
