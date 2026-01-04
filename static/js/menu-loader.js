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
        
        // O item "Início" sempre fica visível
        
        // Inicializar componentes do Bootstrap após carregar o menu
        inicializarBootstrap();
        
        // Exibir nome do usuário no menu
        exibirNomeUsuario();
        
        console.log('Menu carregado com sucesso');
        
    } catch (error) {
        console.error('Erro ao carregar menu:', error);
    }
}

// Função para inicializar componentes do Bootstrap
function inicializarBootstrap() {
    // Verificar se o Bootstrap está disponível
    if (typeof bootstrap === 'undefined') {
        console.error('Bootstrap não está carregado!');
        return;
    }
    
    // Inicializar todos os dropdowns
    const dropdowns = document.querySelectorAll('[data-bs-toggle="dropdown"]');
    dropdowns.forEach(dropdown => {
        new bootstrap.Dropdown(dropdown);
    });
    
    // Inicializar o collapse do navbar (para mobile)
    const navbarToggler = document.querySelector('.navbar-toggler');
    const navbarCollapse = document.querySelector('.navbar-collapse');
    
    if (navbarToggler && navbarCollapse) {
        new bootstrap.Collapse(navbarCollapse, {
            toggle: false
        });
    }
    
    console.log('Bootstrap inicializado no menu');
}

// Função para exibir o nome do usuário no menu
function exibirNomeUsuario() {
    const menuUserName = document.getElementById('menuUserName');
    
    if (menuUserName) {
        const usuarioNome = localStorage.getItem('usuario_nome');
        
        if (usuarioNome) {
            // Extrair primeiro e segundo nome
            const nomes = usuarioNome.trim().split(/\s+/);
            let nomeExibir = '';
            
            if (nomes.length >= 2) {
                // Primeiro e segundo nome
                nomeExibir = `${nomes[0]} ${nomes[1]}`;
            } else if (nomes.length === 1) {
                // Apenas primeiro nome
                nomeExibir = nomes[0];
            }
            
            menuUserName.textContent = nomeExibir;
        }
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
        // Limpar o localStorage
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
        // Reabilitar o botão
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
    // Se o DOM já está carregado, carregar imediatamente
    carregarMenu();
}