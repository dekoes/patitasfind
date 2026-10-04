const API_URL = 'http://localhost:8001';

// State
let token = localStorage.getItem('patitas_token') || '';
let currentUser = null;
let discoverDogs = [];
let currentDogIndex = 0;
let currentMatchId = null;
let currentConversationId = null;
let ws = null;
let cart = JSON.parse(localStorage.getItem('patitas_cart') || '[]');

// DOM refs
const authScreen = document.getElementById('auth-screen');
const mainScreen = document.getElementById('main-screen');
const authForm = document.getElementById('auth-form');
const registerFields = document.getElementById('register-fields');
const authToggle = document.getElementById('auth-toggle');
const authToggleText = document.getElementById('auth-toggle-text');
const authSubmit = document.getElementById('auth-submit');
const logoutBtn = document.getElementById('logout-btn');
const navLogout = document.getElementById('nav-logout');
const topbarNotifications = document.getElementById('topbar-notifications');
const toastEl = document.getElementById('toast');

const views = {
  discover: document.getElementById('discover-view'),
  questionnaire: document.getElementById('questionnaire-view'),
  matches: document.getElementById('matches-view'),
  application: document.getElementById('application-view'),
  chat: document.getElementById('chat-view'),
  publish: document.getElementById('publish-view'),
  notifications: document.getElementById('notifications-view'),
  refuges: document.getElementById('refuges-view'),
  ranking: document.getElementById('ranking-view'),
  shop: document.getElementById('shop-view'),
  lost: document.getElementById('lost-view'),
  foster: document.getElementById('foster-view'),
  more: document.getElementById('more-view'),
};

const navItems = document.querySelectorAll('.nav-item[data-view]');

// Helpers
function showToast(message, type = 'info') {
  toastEl.textContent = message;
  toastEl.classList.add('show');
  setTimeout(() => toastEl.classList.remove('show'), 3000);
}

async function apiFetch(path, options = {}) {
  const url = `${API_URL}${path}`;
  const headers = { ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (options.body && typeof options.body === 'string' && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function formatAge(years, months) {
  const parts = [];
  if (years) parts.push(`${years} año${years > 1 ? 's' : ''}`);
  if (months) parts.push(`${months} mes${months > 1 ? 'es' : ''}`);
  return parts.length ? parts.join(' y ') : 'Edad no especificada';
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

// Navigation
function showScreen(name) {
  if (name === 'auth') {
    authScreen.classList.add('active');
    mainScreen.classList.remove('active');
    return;
  }
  authScreen.classList.remove('active');
  mainScreen.classList.add('active');

  Object.values(views).forEach(v => v.classList.remove('active'));
  if (views[name]) views[name].classList.add('active');

  navItems.forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === name);
  });

  if (name === 'discover') loadDiscover();
  if (name === 'matches') loadMatches();
  if (name === 'notifications') loadNotifications();
  if (name === 'refuges') loadRefuge();
  if (name === 'ranking') loadRanking();
  if (name === 'shop') loadShop();
  if (name === 'lost') loadLostReports();
  if (name === 'foster') loadFoster();
  if (name === 'more') renderMore();
}

// Auth
let isRegister = false;

authToggle.addEventListener('click', () => {
  isRegister = !isRegister;
  registerFields.classList.toggle('hidden', !isRegister);
  authSubmit.textContent = isRegister ? 'Crear cuenta' : 'Iniciar sesión';
  authToggleText.textContent = isRegister ? '¿Ya tenés cuenta?' : '¿No tenés cuenta?';
  authToggle.textContent = isRegister ? 'Iniciá sesión' : 'Registrate';
});

authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;

  try {
    if (isRegister) {
      const full_name = document.getElementById('full_name').value.trim();
      const phone = document.getElementById('phone').value.trim();
      if (!full_name) return showToast('El nombre es obligatorio');
      await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password, full_name, phone }),
      });
      showToast('Cuenta creada, ahora iniciá sesión');
      isRegister = false;
      registerFields.classList.add('hidden');
      authSubmit.textContent = 'Iniciar sesión';
      authToggleText.textContent = '¿No tenés cuenta?';
      authToggle.textContent = 'Registrate';
      return;
    }

    const params = new URLSearchParams();
    params.append('username', email);
    params.append('password', password);
    const data = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: params,
    }).then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Credenciales inválidas');
      }
      return res.json();
    });
    token = data.access_token;
    localStorage.setItem('patitas_token', token);
    await loadUser();
    showScreen('discover');
    showToast(`¡Hola, ${currentUser.full_name}!`);
  } catch (err) {
    showToast(err.message);
  }
});

async function loadUser() {
  currentUser = await apiFetch('/users/me');
}

function logout() {
  token = '';
  currentUser = null;
  currentMatchId = null;
  currentConversationId = null;
  closeWebSocket();
  localStorage.removeItem('patitas_token');
  authForm.reset();
  showScreen('auth');
}

logoutBtn.addEventListener('click', logout);
if (navLogout) navLogout.addEventListener('click', logout);
if (topbarNotifications) topbarNotifications.addEventListener('click', () => showScreen('notifications'));

// Discover
const discoverCard = document.getElementById('discover-card');
const discoverEmpty = document.getElementById('discover-empty');
const dogPhoto = document.getElementById('dog-photo');
const dogName = document.getElementById('dog-name');
const dogBreed = document.getElementById('dog-breed');
const dogAge = document.getElementById('dog-age');
const dogSize = document.getElementById('dog-size');
const dogDescription = document.getElementById('dog-description');
const dogLocation = document.getElementById('dog-location');

async function loadDiscover() {
  try {
    discoverDogs = await apiFetch('/dogs/discover?limit=50');
    currentDogIndex = 0;
    renderCurrentDog();
  } catch (err) {
    showToast(err.message);
  }
}

function renderCurrentDog() {
  const dog = discoverDogs[currentDogIndex];
  if (!dog) {
    discoverCard.classList.add('hidden');
    discoverEmpty.classList.remove('hidden');
    return;
  }
  discoverCard.classList.remove('hidden');
  discoverEmpty.classList.add('hidden');

  dogPhoto.src = dog.photos && dog.photos.length ? dog.photos[0] : 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="%23DCC7FA"/><circle cx="50" cy="50" r="20" fill="%231D2233"/></svg>';
  dogPhoto.alt = dog.name;
  dogName.textContent = dog.name;
  dogBreed.textContent = dog.breed || 'Raza desconocida';
  dogAge.textContent = formatAge(dog.age_years, dog.age_months);
  dogSize.textContent = dog.size || 'Tamaño no especificado';
  dogDescription.textContent = dog.description || 'Sin descripción';
  dogLocation.textContent = [dog.city, dog.country].filter(Boolean).join(', ') || 'Ubicación no especificada';
}

document.getElementById('skip-btn').addEventListener('click', () => {
  currentDogIndex++;
  renderCurrentDog();
});

document.getElementById('reload-discover').addEventListener('click', loadDiscover);

document.getElementById('like-btn').addEventListener('click', async () => {
  const dog = discoverDogs[currentDogIndex];
  if (!dog) return;
  try {
    const match = await apiFetch(`/dogs/${dog.id}/like`, { method: 'POST' });
    currentMatchId = match.id;
    document.getElementById('match-dog-name').textContent = dog.name;
    document.getElementById('q-dog-name').textContent = dog.name;
    document.getElementById('match-modal').classList.remove('hidden');
    currentDogIndex++;
    renderCurrentDog();
  } catch (err) {
    showToast(err.message);
  }
});

// Match modal
document.getElementById('match-questionnaire').addEventListener('click', () => {
  document.getElementById('match-modal').classList.add('hidden');
  showScreen('questionnaire');
});

document.getElementById('match-close').addEventListener('click', () => {
  document.getElementById('match-modal').classList.add('hidden');
});

// Questionnaire
document.getElementById('questionnaire-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!currentMatchId) return showToast('No hay un match activo');
  const answers = {
    housing: document.getElementById('housing').value,
    experience: document.getElementById('experience').value,
    children: document.getElementById('children').value,
    other_pets: document.getElementById('other_pets').value,
    budget: document.getElementById('budget').value,
    outdoor: document.getElementById('outdoor').value,
  };
  try {
    await apiFetch(`/matches/${currentMatchId}/apply`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    });
    showToast('Cuestionario enviado');
    currentMatchId = null;
    document.getElementById('questionnaire-form').reset();
    showScreen('matches');
  } catch (err) {
    showToast(err.message);
  }
});

document.getElementById('q-cancel').addEventListener('click', () => {
  currentMatchId = null;
  document.getElementById('questionnaire-form').reset();
  showScreen('discover');
});

// Matches
let matchesData = [];

async function loadMatches() {
  try {
    matchesData = await apiFetch('/matches');
    const list = document.getElementById('matches-list');
    if (!matchesData.length) {
      list.innerHTML = '<p class="empty-text">Todavía no tenés matches.</p>';
      return;
    }
    list.innerHTML = matchesData.map(m => renderMatchCard(m)).join('');
  } catch (err) {
    showToast(err.message);
  }
}

function renderMatchCard(m) {
  const isOwner = currentUser && m.dog && m.dog.owner_id === currentUser.id;
  const thumb = m.dog.photos && m.dog.photos.length ? m.dog.photos[0] : 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="%23DCC7FA"/></svg>';
  const otherName = isOwner ? m.user.full_name : (m.dog.owner_name || 'Dueño');
  const statusClass = `status-${m.status}`;
  let actions = '';

  if (isOwner) {
    if (m.status === 'pending_application') {
      actions = `
        <button class="btn btn-sm btn-ghost" onclick="viewApplication(${m.id})">Ver cuestionario</button>
        <button class="btn btn-sm btn-green" onclick="approveMatch(${m.id})">Aprobar</button>
        <button class="btn btn-sm btn-red" onclick="rejectMatch(${m.id})">Rechazar</button>
      `;
    } else if (m.status === 'approved') {
      actions = `
        <button class="btn btn-sm btn-primary" onclick="openChat(${m.id})">Abrir chat</button>
        <button class="btn btn-sm btn-ghost" onclick="openReminders(${m.id})">Recordatorios</button>
      `;
    }
  } else {
    if (m.status === 'approved') {
      actions = `
        <button class="btn btn-sm btn-primary" onclick="openChat(${m.id})">Abrir chat</button>
        <button class="btn btn-sm btn-ghost" onclick="openReminders(${m.id})">Recordatorios</button>
      `;
    } else if (m.status === 'pending_application') {
      actions = `<button class="btn btn-sm btn-ghost" onclick="fillApplication(${m.id})">Ver cuestionario</button>`;
    }
  }

  return `
    <div class="match-card">
      <div class="match-thumb"><img src="${thumb}" alt="${m.dog.name}"></div>
      <div class="match-body">
        <h3>${m.dog.name}</h3>
        <p>${isOwner ? 'Solicitante' : 'Publicado por'}: ${otherName}</p>
        <span class="status-badge ${statusClass}">${m.status.replace('_', ' ')}</span>
        <div class="match-actions">${actions}</div>
      </div>
    </div>
  `;
}

window.approveMatch = async (id) => {
  try {
    const conversation = await apiFetch(`/matches/${id}/approve`, { method: 'POST' });
    showToast('Solicitud aprobada');
    loadMatches();
  } catch (err) {
    showToast(err.message);
  }
};

window.rejectMatch = async (id) => {
  try {
    await apiFetch(`/matches/${id}/reject`, { method: 'POST' });
    showToast('Solicitud rechazada');
    loadMatches();
  } catch (err) {
    showToast(err.message);
  }
};

window.viewApplication = async (id) => {
  try {
    const app = await apiFetch(`/matches/${id}/application`);
    const m = matchesData.find(x => x.id === id);
    document.getElementById('app-adopter-name').textContent = m.user.full_name;
    document.getElementById('app-dog-name').textContent = m.dog.name;
    const container = document.getElementById('application-answers');
    const labels = {
      housing: 'Vivienda',
      experience: 'Experiencia',
      children: 'Niños en casa',
      other_pets: 'Otras mascotas',
      budget: 'Presupuesto mensual',
      outdoor: 'Espacio exterior',
    };
    container.innerHTML = Object.entries(app.answers).map(([k, v]) => `
      <div class="answer-row">
        <strong>${labels[k] || k}</strong>
        <span>${v}</span>
      </div>
    `).join('');
    showScreen('application');
  } catch (err) {
    showToast(err.message);
  }
};

document.getElementById('app-back').addEventListener('click', () => showScreen('matches'));

window.fillApplication = async (id) => {
  currentMatchId = id;
  const m = matchesData.find(x => x.id === id);
  document.getElementById('q-dog-name').textContent = m ? m.dog.name : 'este perro';
  showScreen('questionnaire');
};

// Chat
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatForm = document.getElementById('chat-form');

document.getElementById('chat-back').addEventListener('click', () => {
  closeWebSocket();
  showScreen('matches');
});

window.openChat = async (matchId) => {
  try {
    const conversations = await apiFetch('/conversations');
    const conversation = conversations.find(c => c.match_id === matchId);
    if (!conversation) {
      return showToast('La conversación aún no está disponible. Asegurate de que el dueño aprobó la solicitud.');
    }
    currentConversationId = conversation.id;
    const m = matchesData.find(x => x.id === matchId);
    const isOwner = currentUser && m.dog.owner_id === currentUser.id;
    const chatWith = isOwner ? m.user.full_name : (m.dog.owner_name || 'Dueño');
    document.getElementById('chat-dog-name').textContent = m.dog.name;
    document.getElementById('chat-with').textContent = `con ${chatWith}`;
    chatMessages.innerHTML = '';
    showScreen('chat');
    await loadChatHistory(conversation.id);
    connectWebSocket(conversation.id);
  } catch (err) {
    showToast(err.message);
  }
};

async function loadChatHistory(conversationId) {
  try {
    const messages = await apiFetch(`/conversations/${conversationId}/messages?limit=50`);
    messages.reverse().forEach(renderMessage);
  } catch (err) {
    showToast(err.message);
  }
}

function renderMessage(msg) {
  const own = msg.sender_id === currentUser.id;
  const div = document.createElement('div');
  div.className = `message ${own ? 'own' : 'other'}`;
  div.innerHTML = `<div>${escapeHtml(msg.content)}</div><time>${formatDate(msg.created_at)}</time>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function connectWebSocket(conversationId) {
  closeWebSocket();
  const wsUrl = `ws://localhost:8001/ws/chat/${conversationId}?token=${encodeURIComponent(token)}`;
  ws = new WebSocket(wsUrl);
  ws.onopen = () => console.log('WS connected');
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    renderMessage(msg);
  };
  ws.onerror = () => showToast('Error de conexión de chat');
  ws.onclose = () => console.log('WS closed');
}

function closeWebSocket() {
  if (ws) {
    ws.close();
    ws = null;
  }
}

chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const content = chatInput.value.trim();
  if (!content || !ws) return;
  ws.send(JSON.stringify({ content }));
  chatInput.value = '';
});

// Publish
document.getElementById('publish-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const photosRaw = document.getElementById('pub-photos').value;
  const photos = photosRaw.split(',').map(s => s.trim()).filter(Boolean);
  const payload = {
    name: document.getElementById('pub-name').value.trim(),
    breed: document.getElementById('pub-breed').value.trim() || null,
    age_years: parseInt(document.getElementById('pub-age-years').value) || null,
    age_months: parseInt(document.getElementById('pub-age-months').value) || null,
    size: document.getElementById('pub-size').value || null,
    description: document.getElementById('pub-description').value.trim() || null,
    city: document.getElementById('pub-city').value.trim() || null,
    country: document.getElementById('pub-country').value.trim() || null,
    photos,
  };
  try {
    await apiFetch('/dogs', { method: 'POST', body: JSON.stringify(payload) });
    showToast('Perro publicado');
    document.getElementById('publish-form').reset();
    showScreen('discover');
  } catch (err) {
    showToast(err.message);
  }
});

// Notifications
async function loadNotifications() {
  try {
    const notifications = await apiFetch('/notifications');
    const list = document.getElementById('notifications-list');
    const unread = notifications.filter(n => !n.is_read);
    updateNotifBadge(unread.length);

    if (!notifications.length) {
      list.innerHTML = '<p class="empty-text">No tenés notificaciones.</p>';
      return;
    }

    list.innerHTML = notifications.map(n => `
      <div class="notif-card ${n.is_read ? '' : 'unread'}">
        <strong>${escapeHtml(n.title)}</strong>
        <p>${escapeHtml(n.body)}</p>
        <time>${formatDate(n.created_at)}</time>
      </div>
    `).join('');

    if (unread.length) {
      await apiFetch('/notifications/read-all', { method: 'PATCH' });
      updateNotifBadge(0);
    }
  } catch (err) {
    showToast(err.message);
  }
}

function updateNotifBadge(count) {
  const badge = document.getElementById('notif-badge');
  badge.textContent = count;
  badge.classList.toggle('hidden', count === 0);
}

async function refreshNotifCount() {
  try {
    const notifications = await apiFetch('/notifications');
    const unread = notifications.filter(n => !n.is_read).length;
    updateNotifBadge(unread);
  } catch {}
}

// Bottom nav
navItems.forEach(btn => {
  btn.addEventListener('click', () => showScreen(btn.dataset.view));
});

// More grid
document.querySelectorAll('.more-btn[data-view]').forEach(btn => {
  btn.addEventListener('click', () => showScreen(btn.dataset.view));
});
document.getElementById('more-logout')?.addEventListener('click', logout);

// Refuges
let myRefuge = null;

const refugeInfo = document.getElementById('refuge-info');
const refugeForm = document.getElementById('refuge-form');
const refugeName = document.getElementById('refuge-name');
const refugeStatus = document.getElementById('refuge-status');
const refugeDescription = document.getElementById('refuge-description');
const refugeLocation = document.getElementById('refuge-location');
const refugeActions = document.getElementById('refuge-actions');

async function loadRefuge() {
  try {
    myRefuge = await apiFetch('/refuges/me');
    renderRefuge();
  } catch (err) {
    if (err.message.includes('404') || err.message.includes('not found')) {
      myRefuge = null;
      renderRefugeForm();
    } else {
      showToast(err.message);
    }
  }
}

function renderRefuge() {
  if (!myRefuge) return renderRefugeForm();
  refugeForm.classList.add('hidden');
  refugeInfo.classList.remove('hidden');

  refugeName.textContent = myRefuge.name;
  refugeStatus.textContent = myRefuge.status;
  refugeStatus.className = `status-badge status-${myRefuge.status}`;
  refugeDescription.textContent = myRefuge.description || 'Sin descripción';
  refugeLocation.textContent = [myRefuge.city, myRefuge.country].filter(Boolean).join(', ') || 'Ubicación no especificada';

  document.getElementById('stat-rescued').textContent = myRefuge.rescued_count;
  document.getElementById('stat-adopted').textContent = myRefuge.adopted_count;
  document.getElementById('stat-foster').textContent = myRefuge.foster_count;
  document.getElementById('stat-points').textContent = myRefuge.points;

  const isApproved = myRefuge.status === 'approved';
  refugeActions.classList.toggle('hidden', !isApproved);
}

function renderRefugeForm() {
  refugeInfo.classList.add('hidden');
  refugeForm.classList.remove('hidden');
}

refugeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const documentsRaw = document.getElementById('ref-documents').value;
  const payload = {
    name: document.getElementById('ref-name').value.trim(),
    description: document.getElementById('ref-description-input').value.trim() || null,
    city: document.getElementById('ref-city').value.trim() || null,
    country: document.getElementById('ref-country').value.trim() || null,
    documents: documentsRaw.split(',').map(s => s.trim()).filter(Boolean),
  };
  try {
    myRefuge = await apiFetch('/refuges/register', { method: 'POST', body: JSON.stringify(payload) });
    currentUser.role = 'refuge';
    showToast('Refugio registrado. Esperá aprobación.');
    renderRefuge();
  } catch (err) {
    showToast(err.message);
  }
});

async function doRefugeAction(action) {
  if (!myRefuge) return;
  try {
    myRefuge = await apiFetch(`/refuges/${myRefuge.id}/${action}`, { method: 'POST' });
    showToast('Registro guardado');
    renderRefuge();
  } catch (err) {
    showToast(err.message);
  }
}

document.getElementById('btn-rescue').addEventListener('click', () => doRefugeAction('rescue'));
document.getElementById('btn-adopt').addEventListener('click', () => doRefugeAction('adopt'));
document.getElementById('btn-foster').addEventListener('click', () => doRefugeAction('foster'));

// Ranking
async function loadRanking() {
  try {
    const ranking = await apiFetch('/refuges/ranking');
    const list = document.getElementById('ranking-list');
    if (!ranking.length) {
      list.innerHTML = '<p class="empty-text">Todavía no hay refugios en el ranking.</p>';
      return;
    }
    list.innerHTML = ranking.map((r, i) => `
      <div class="ranking-card">
        <div class="ranking-position">${i + 1}</div>
        <div class="ranking-body">
          <h3>${escapeHtml(r.name)}</h3>
          <p>${[r.city, r.country].filter(Boolean).join(', ') || 'Ubicación no especificada'}</p>
          <div class="ranking-stats">
            <span class="badge">${r.points} pts</span>
            <span class="badge">${r.adopted_count} adopciones</span>
            <span class="badge">${r.rescued_count} rescates</span>
          </div>
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast(err.message);
  }
}

// Shop
let productsData = [];

function saveCart() {
  localStorage.setItem('patitas_cart', JSON.stringify(cart));
  updateCartCount();
}

function updateCartCount() {
  const count = cart.reduce((sum, item) => sum + item.quantity, 0);
  const el = document.getElementById('cart-count');
  if (el) el.textContent = count;
}

function addToCart(productId) {
  const product = productsData.find(p => p.id === productId);
  if (!product) return;
  const existing = cart.find(item => item.product_id === productId);
  if (existing) {
    existing.quantity += 1;
  } else {
    cart.push({ product_id: productId, name: product.name, price: product.price, quantity: 1 });
  }
  saveCart();
  showToast(`${product.name} agregado al carrito`);
}

function removeFromCart(productId) {
  cart = cart.filter(item => item.product_id !== productId);
  saveCart();
  renderCart();
}

function changeCartQty(productId, delta) {
  const item = cart.find(i => i.product_id === productId);
  if (!item) return;
  item.quantity += delta;
  if (item.quantity <= 0) {
    removeFromCart(productId);
    return;
  }
  saveCart();
  renderCart();
}

function renderCart() {
  const container = document.getElementById('cart-items');
  if (!cart.length) {
    container.innerHTML = '<p class="empty-text">El carrito está vacío.</p>';
    document.getElementById('cart-total').textContent = '$0';
    return;
  }
  const total = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
  container.innerHTML = cart.map(item => `
    <div class="cart-item">
      <div class="cart-item-info">
        <strong>${escapeHtml(item.name)}</strong>
        <span>$${item.price} c/u</span>
      </div>
      <div class="cart-item-qty">
        <button onclick="changeCartQty(${item.product_id}, -1)">-</button>
        <span>${item.quantity}</span>
        <button onclick="changeCartQty(${item.product_id}, 1)">+</button>
      </div>
    </div>
  `).join('');
  document.getElementById('cart-total').textContent = `$${total.toFixed(2)}`;
}

window.changeCartQty = changeCartQty;

async function loadShop() {
  updateCartCount();
  try {
    productsData = await apiFetch('/products');
    const list = document.getElementById('shop-list');
    if (!productsData.length) {
      list.innerHTML = '<p class="empty-text">No hay productos disponibles.</p>';
    } else {
      list.innerHTML = productsData.map(p => `
        <div class="product-card">
          <div class="product-thumb"><img src="${p.photos && p.photos.length ? p.photos[0] : 'data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\"><rect width=\"64\" height=\"64\" fill=\"%23DCC7FA\"/></svg>'}" alt="${escapeHtml(p.name)}"></div>
          <div class="product-body">
            <h3>${escapeHtml(p.name)}</h3>
            <p>${escapeHtml(p.description || '')}</p>
            <div class="product-meta">
              <span class="product-price">$${p.price}</span>
              <span class="badge">${p.stock} disp.</span>
            </div>
            <button class="btn btn-primary btn-sm" onclick="addToCart(${p.id})">Agregar al carrito</button>
          </div>
        </div>
      `).join('');
    }
    await loadOrders();
  } catch (err) {
    showToast(err.message);
  }
}

window.addToCart = addToCart;

async function loadOrders() {
  try {
    const orders = await apiFetch('/orders');
    const list = document.getElementById('orders-list');
    if (!orders.length) {
      list.innerHTML = '<p class="empty-text">Todavía no hiciste pedidos.</p>';
      return;
    }
    list.innerHTML = orders.map(o => `
      <div class="order-card">
        <div class="order-header">
          <strong>Pedido #${o.id}</strong>
          <span class="status-badge status-${o.status}">${o.status}</span>
        </div>
        <p>Total: $${o.total}</p>
        <p>${escapeHtml(o.shipping_address)}</p>
        <div class="order-items">
          ${o.items.map(i => `<span class="badge">${i.quantity}x ${escapeHtml(i.product.name)}</span>`).join('')}
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast(err.message);
  }
}

document.getElementById('cart-btn')?.addEventListener('click', () => {
  renderCart();
  document.getElementById('cart-modal').classList.remove('hidden');
});

document.getElementById('cart-close')?.addEventListener('click', () => {
  document.getElementById('cart-modal').classList.add('hidden');
});

document.getElementById('cart-checkout')?.addEventListener('click', async () => {
  if (!cart.length) return showToast('El carrito está vacío');
  const address = document.getElementById('cart-address').value.trim();
  if (!address) return showToast('Ingresá una dirección de envío');
  try {
    const items = cart.map(({ product_id, quantity }) => ({ product_id, quantity }));
    await apiFetch('/orders', {
      method: 'POST',
      body: JSON.stringify({ items, shipping_address: address }),
    });
    showToast('Pedido realizado');
    cart = [];
    saveCart();
    document.getElementById('cart-address').value = '';
    document.getElementById('cart-modal').classList.add('hidden');
    loadOrders();
  } catch (err) {
    showToast(err.message);
  }
});

// Lost reports
async function loadLostReports() {
  try {
    const reports = await apiFetch('/lost-reports');
    const list = document.getElementById('lost-list');
    if (!reports.length) {
      list.innerHTML = '<p class="empty-text">No hay reportes activos.</p>';
      return;
    }
    list.innerHTML = reports.map(r => `
      <div class="lost-card">
        <div class="lost-thumb"><img src="${r.photos && r.photos.length ? r.photos[0] : 'data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\"><rect width=\"64\" height=\"64\" fill=\"%23DCC7FA\"/></svg>'}" alt="${escapeHtml(r.dog_name)}"></div>
        <div class="lost-body">
          <h3>${escapeHtml(r.dog_name)}</h3>
          <p>${[r.city, r.country].filter(Boolean).join(', ') || 'Ubicación no especificada'}</p>
          <p class="lost-desc">${escapeHtml(r.description || '')}</p>
        </div>
      </div>
    `).join('');
  } catch (err) {
    showToast(err.message);
  }
}

document.getElementById('lost-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const photosRaw = document.getElementById('lost-photos').value;
  const payload = {
    dog_name: document.getElementById('lost-dog-name').value.trim(),
    description: document.getElementById('lost-description').value.trim() || null,
    city: document.getElementById('lost-city').value.trim() || null,
    country: document.getElementById('lost-country').value.trim() || null,
    photos: photosRaw.split(',').map(s => s.trim()).filter(Boolean),
  };
  try {
    await apiFetch('/lost-reports', { method: 'POST', body: JSON.stringify(payload) });
    showToast('Reporte publicado');
    document.getElementById('lost-form').reset();
    loadLostReports();
  } catch (err) {
    showToast(err.message);
  }
});

// Foster homes
let myFosterHome = null;

async function loadFoster() {
  try {
    myFosterHome = await apiFetch('/foster-homes/me');
    renderMyFosterHome();
  } catch (err) {
    myFosterHome = null;
    renderFosterForm();
  }
  try {
    const homes = await apiFetch('/foster-homes');
    const list = document.getElementById('foster-list');
    if (!homes.length) {
      list.innerHTML = '<p class="empty-text">No hay casas de paso aprobadas.</p>';
      return;
    }
    list.innerHTML = homes.map(h => `
      <div class="foster-card">
        <h3>${escapeHtml(h.user.full_name || 'Casa de paso')}</h3>
        <p>${[h.city, h.country].filter(Boolean).join(', ') || 'Ubicación no especificada'}</p>
        <p class="foster-desc">${escapeHtml(h.description || '')}</p>
        <span class="badge">Capacidad: ${h.capacity}</span>
      </div>
    `).join('');
  } catch (err) {
    showToast(err.message);
  }
}

function renderMyFosterHome() {
  if (!myFosterHome) return renderFosterForm();
  document.getElementById('foster-form').classList.add('hidden');
  document.getElementById('foster-my-info').classList.remove('hidden');
  document.getElementById('foster-my-status').textContent = myFosterHome.status;
  document.getElementById('foster-my-status').className = `status-badge status-${myFosterHome.status}`;
  document.getElementById('foster-my-description').textContent = myFosterHome.description || 'Sin descripción';
  document.getElementById('foster-my-location').textContent = [myFosterHome.city, myFosterHome.country].filter(Boolean).join(', ') || 'Ubicación no especificada';
}

function renderFosterForm() {
  document.getElementById('foster-my-info').classList.add('hidden');
  document.getElementById('foster-form').classList.remove('hidden');
}

document.getElementById('foster-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    description: document.getElementById('foster-description').value.trim() || null,
    city: document.getElementById('foster-city').value.trim() || null,
    country: document.getElementById('foster-country').value.trim() || null,
    capacity: parseInt(document.getElementById('foster-capacity').value) || 1,
  };
  try {
    myFosterHome = await apiFetch('/foster-homes/register', { method: 'POST', body: JSON.stringify(payload) });
    currentUser.role = 'foster';
    showToast('Casa de paso registrada. Esperá aprobación.');
    renderMyFosterHome();
  } catch (err) {
    showToast(err.message);
  }
});

// Reminders
let remindersMatchId = null;

window.openReminders = async (matchId) => {
  remindersMatchId = matchId;
  document.getElementById('reminder-match-id').value = matchId;
  document.getElementById('reminders-modal').classList.remove('hidden');
  await loadReminders(matchId);
};

async function loadReminders(matchId) {
  try {
    const reminders = await apiFetch('/reminders');
    const list = document.getElementById('reminders-list-modal');
    const matchReminders = reminders.filter(r => r.match_id === matchId);
    if (!matchReminders.length) {
      list.innerHTML = '<p class="empty-text">Sin recordatorios.</p>';
      return;
    }
    list.innerHTML = matchReminders.map(r => `
      <div class="reminder-card ${r.is_completed ? 'completed' : ''}">
        <div>
          <strong>${escapeHtml(r.title)}</strong>
          <span class="badge">${r.type}</span>
          <p>${formatDate(r.due_date)}</p>
        </div>
        ${r.is_completed ? '<span class="badge">Completado</span>' : `<button class="btn btn-sm btn-green" onclick="completeReminder(${r.id})">Completar</button>`}
      </div>
    `).join('');
  } catch (err) {
    showToast(err.message);
  }
}

window.completeReminder = async (id) => {
  try {
    await apiFetch(`/reminders/${id}/complete`, { method: 'PATCH' });
    showToast('Recordatorio completado');
    loadReminders(remindersMatchId);
  } catch (err) {
    showToast(err.message);
  }
};

document.getElementById('reminder-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const matchId = parseInt(document.getElementById('reminder-match-id').value);
  const payload = {
    match_id: matchId,
    title: document.getElementById('reminder-title').value.trim(),
    type: document.getElementById('reminder-type').value,
    due_date: new Date(document.getElementById('reminder-due').value).toISOString(),
  };
  try {
    await apiFetch('/reminders', { method: 'POST', body: JSON.stringify(payload) });
    showToast('Recordatorio creado');
    document.getElementById('reminder-form').reset();
    document.getElementById('reminder-match-id').value = matchId;
    loadReminders(matchId);
  } catch (err) {
    showToast(err.message);
  }
});

document.getElementById('reminders-close')?.addEventListener('click', () => {
  document.getElementById('reminders-modal').classList.add('hidden');
  remindersMatchId = null;
});

function renderMore() {
  // Nothing dynamic required; grid buttons handled globally.
}

// Init
async function init() {
  if (token) {
    try {
      await loadUser();
      showScreen('discover');
      refreshNotifCount();
    } catch {
      logout();
    }
  } else {
    showScreen('auth');
  }
}

init();
