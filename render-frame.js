// Rasterise one already-baked (animation-free) SVG frame to PNG.
// Used by verify.py; needs `npm install` once for @resvg/resvg-js.
//   node render-frame.js in.svg out.png [scale]
const fs = require('fs');
const { Resvg } = require('@resvg/resvg-js');
const [src, dst, scale = '1'] = process.argv.slice(2);
const resvg = new Resvg(fs.readFileSync(src, 'utf8'), {
  fitTo: { mode: 'width', value: 900 * Number(scale) },
  background: 'rgba(255,255,255,0)',
});
fs.writeFileSync(dst, resvg.render().asPng());
