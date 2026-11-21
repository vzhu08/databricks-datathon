import { initialTurn, sampleTranscript, turnReducer } from '../src/index';
console.log('FIXTURE text; not a transcription of the tone.wav test audio', sampleTranscript);
let turn = turnReducer(initialTurn, { type: 'record' });
turn = turnReducer(turn, { type: 'stop' });
turn = turnReducer(turn, { type: 'transcript', text: sampleTranscript.text });
turn = turnReducer(turn, {
  type: 'reply',
  text: 'Sample response: the garden satisfies the accessibility and budget constraints.',
});
console.log(turn);
console.log('Completed fixture turn', turnReducer(turn, { type: 'played' }));
