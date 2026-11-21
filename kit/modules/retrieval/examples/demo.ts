import { LocalIndex, answerFromResults, evaluateRetrieval } from '../src/index';
import { normalizeText } from '../../documents/src/index';
import corpus from '../fixtures/corpus.json';
import cases from '../fixtures/evaluation.json';
const index = new LocalIndex();
corpus.forEach((document) => index.upsert(normalizeText(document)));
console.log(
  JSON.stringify(
    {
      mode: 'local',
      answer: answerFromResults(
        'fresh vegetables',
        index.search('fresh vegetables'),
        index.getDocuments(),
      ),
      evaluation: evaluateRetrieval(index, cases),
    },
    null,
    2,
  ),
);
