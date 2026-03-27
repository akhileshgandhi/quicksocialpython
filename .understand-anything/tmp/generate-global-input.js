const fs = require('fs');
const scanResults = JSON.parse(fs.readFileSync('.understand-anything/intermediate/scan-result.json', 'utf8'));

const input = {
  projectRoot: process.cwd().replace(/\\/g, '/'),
  allProjectFiles: scanResults.files.map(f => f.path),
  batchFiles: scanResults.files
};

fs.writeFileSync('.understand-anything/tmp/ua-file-analyzer-input-all.json', JSON.stringify(input, null, 2));
console.log('Global extraction input prepared.');
