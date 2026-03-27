const fs = require('fs');
const batchAll = JSON.parse(fs.readFileSync('.understand-anything/intermediate/batch-all.json', 'utf8'));
const layers = JSON.parse(fs.readFileSync('.understand-anything/intermediate/layers.json', 'utf8'));

const input = {
  nodes: batchAll.nodes,
  edges: batchAll.edges,
  layers: layers
};

fs.writeFileSync('.understand-anything/tmp/ua-tour-input.json', JSON.stringify(input, null, 2));
console.log('Tour input prepared.');
