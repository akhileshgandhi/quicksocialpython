const fs = require('fs');
const batchAll = JSON.parse(fs.readFileSync('.understand-anything/intermediate/batch-all.json', 'utf8'));

const input = {
  fileNodes: batchAll.nodes.filter(n => n.type === 'file'),
  importEdges: batchAll.edges.filter(e => e.type === 'imports')
};

fs.writeFileSync('.understand-anything/tmp/ua-arch-input.json', JSON.stringify(input, null, 2));
console.log('Architecture input prepared.');
