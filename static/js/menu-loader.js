// Função para carregar o menu
async function carregarMenu() {
    try {
        const response = await fetch('/static/components/menu.html');
        const menuHtml = await response.text();
        
        // Procura por um container com id 'menu-container' ou cria um
        let menuContainer = document.getElementById('menu-container');
        
        if (!menuContainer) {
            // Se não existe, cria e insere no início do body
            menuContainer = document.createElement('div');
            menuContainer.id = 'menu-container';
            document.body.insertBefore(menuContainer, document.body.firstChild);
        }
        
        menuContainer.innerHTML = menuHtml;
        
        // Determinar se deve mostrar o link "Início"
        const paginaAtual = window.location.pathname;
        const ehPaginaInicial = paginaAtual === '/' || paginaAtual === '/index' || paginaAtual === '/index.html';
        
        if (!ehPaginaInicial) {
            // Se não for a página inicial, mostra o link "Início"
            const menuInicio = document.querySelector('.menu-inicio');
            if (menuInicio) {
                menuInicio.style.display = 'block';
            }
        }
        
    } catch (error) {
        console.error('Erro ao carregar menu:', error);
    }
}

// Função de logout (global para ser acessível pelo onclick)
function fazerLogout() {
    const btnLogout = document.getElementById('btnLogout');
    
    if (!btnLogout) return;
    
    // Desabilitar o botão para evitar múltiplos cliques
    btnLogout.disabled = true;
    btnLogout.textContent = 'Saindo...';
    
    // Fazer requisição para o endpoint de logout do backend
    fetch('/logout', {
        method: 'GET',
        credentials: 'same-origin'
    })
    .then(response => {
        // Independente da resposta, limpar o localStorage
        localStorage.removeItem('usuario_logado');
        localStorage.removeItem('usuario_id');
        localStorage.removeItem('usuario_login');
        localStorage.removeItem('usuario_nome');
        localStorage.removeItem('nivel_acesso');
        
        // Redirecionar para a página de login
        window.location.href = '/login';
    })
    .catch(error => {
        console.error('Erro durante logout:', error);
        
        // Mesmo com erro, limpar o localStorage e redirecionar
        localStorage.removeItem('usuario_logado');
        localStorage.removeItem('usuario_id');
        localStorage.removeItem('usuario_login');
        localStorage.removeItem('usuario_nome');
        localStorage.removeItem('nivel_acesso');
        
        window.location.href = '/login';
    })
    .finally(() => {
        // Reabilitar o botão (caso algo dê errado)
        if (btnLogout) {
            btnLogout.disabled = false;
            btnLogout.textContent = 'Sair';
        }
    });
}

// Carregar o menu quando o DOM estiver pronto
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', carregarMenu);
} else {
    carregarMenu();
}
