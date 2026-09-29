import TurndownService from 'turndown';
import { JSDOM } from 'jsdom';

const dom = new JSDOM();
global.document = dom.window.document;

const ts = new TurndownService();
ts.addRule('tableCell', {
  filter: ['th', 'td'],
  replacement: function(content) {
    return ' ' + content.replace(/\n/g, '<br>') + ' |';
  }
});

ts.addRule('table', {
  filter: 'table',
  replacement: function(content, node) {
    if (node.querySelector('table')) return '\n\n' + node.outerHTML + '\n\n';
    return content;
  }
});

const div = document.createElement('div');
div.innerHTML = '<table><tr><td>Outer</td><td><table><tr><td>Inner</td></tr></table></td></tr></table>';
console.log(ts.turndown(div));
