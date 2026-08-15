import * as esbuild from 'esbuild';

await esbuild.build({
  entryPoints: ['./src/app.js'],
  bundle: true,
  minify: true,
  outfile: './static/js/bundle.js',
  target: 'es2020',
  format: 'iife',
});
