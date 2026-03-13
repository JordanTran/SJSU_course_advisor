const API_URL = 'http://localhost:8000/ask';
const DEFAULT_COURSE = 'ISE 201';

const chat = document.getElementById('chat');
const input = document.getElementById('question');
const courseInput = document.getElementById('course-name');
const sendBtn = document.getElementById('send-btn');

// Set default course name
if (courseInput) courseInput.value = DEFAULT_COURSE;

input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
sendBtn.addEventListener('click', send);

async function send() {
  const question = input.value.trim();
  if (!question) return;

  const courseName = (courseInput ? courseInput.value.trim() : DEFAULT_COURSE) || DEFAULT_COURSE;
  input.value = '';

  chat.innerHTML += `<div class="user"><b>You (${courseName}):</b> ${question}</div>`;

  try {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, course_name: courseName })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Server error ${res.status}`);
    }

    const data = await res.json();
    const div = document.createElement('div');
    div.className = 'advisor';
    div.innerHTML = '<b>Advisor:</b> ';
    const span = document.createElement('span');
    span.textContent = data.answer;
    div.appendChild(span);
    chat.appendChild(div);
  } catch (err) {
    chat.innerHTML += `<div class="advisor error"><b>Error:</b> ${err.message}</div>`;
  }

  chat.scrollTop = chat.scrollHeight;
}
