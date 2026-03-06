const API_URL = 'http://localhost:8000/ask';
const chat = document.getElementById('chat');
const input = document.getElementById('question');
const sendBtn = document.getElementById('send-btn');

input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
sendBtn.addEventListener('click', send);

async function send() {
  const question = input.value.trim();
  if (!question) return;
  input.value = '';

  chat.innerHTML += `<div class="user"><b>You:</b> ${question}</div>`;

  try {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });
    const data = await res.json();
    const div = document.createElement('div');
    div.className = 'advisor';
    div.innerHTML = '<b>Advisor:</b> ';
    const span = document.createElement('span');
    span.textContent = data.answer;
    div.appendChild(span);
    chat.appendChild(div);
  } catch (err) {
    chat.innerHTML += `<div class="advisor"><b>Error:</b> ${err.message}</div>`;
  }

  chat.scrollTop = chat.scrollHeight;
}
