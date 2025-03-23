function verificarAutenticacao() {
    const usuarioLogado = localStorage.getItem('usuario_logado');
    
    // Se não estiver na página de login e não houver usuário logado
    if (window.location.pathname !== '/login' && usuarioLogado !== 'true') {
        window.location.href = '/login';
        return false;
    }
    
    // Se estiver na página de login e houver usuário logado
    if (window.location.pathname === '/login' && usuarioLogado === 'true') {
        window.location.href = '/';
        return false;
    }
    
    // Se estiver em uma página autenticada, adicionar o footer caso ele ainda não exista
    if (usuarioLogado === 'true' && window.location.pathname !== '/login' && !document.querySelector('.footer')) {
        adicionarFooter();
    }
    
    return true;
}

// Executa a verificação quando a página carrega
document.addEventListener('DOMContentLoaded', verificarAutenticacao);

// Função para adicionar o footer dinâmicamente
function adicionarFooter() {
    // Apenas adicione o footer se ele ainda não existir na página
    if (!document.querySelector('.footer')) {
        // Adicionar os estilos CSS
        const style = document.createElement('style');
        style.textContent = `
            body {
                padding-bottom: 50px; /* Espaço para o footer */
            }
            .footer {
                background-color: #343a40;
                color: white;
                padding: 10px 0;
                width: 100%;
                position: fixed;
                bottom: 0;
                left: 0;
                z-index: 1000;
            }
            .footer-content {
                display: flex;
                justify-content: space-between;
                align-items: center;
                max-width: 1140px;
                margin: 0 auto;
                padding: 0 15px;
            }
            .footer-content .btn-logout {
                color: white;
                background-color: transparent;
                border: 1px solid rgba(255,255,255,0.5);
            }
            .footer-content .btn-logout:hover {
                background-color: rgba(255,255,255,0.1);
            }
        `;
        //document.head.appendChild(style);
        
        // Criar o footer
        // const footer = document.createElement('footer');
        // footer.className = 'footer';
        
        // Obter o nome do usuário
        const usuarioNome = localStorage.getItem('usuario_nome');
        
        // Conteúdo do footer
        // footer.innerHTML = `
        //     <div class="container">
        //         <div class="footer-content">
        //             <div id="userInfo">${usuarioNome || 'Usuário'}</div>
        //             <button class="btn btn-sm btn-logout" onclick="fazerLogout()">Sair</button>
        //         </div>
        //     </div>
        // `;
        
        // Adicionar o footer ao body
        //document.body.appendChild(footer);
    }
}

// Função para fazer logout
function fazerLogout() {
    // Chamar a rota de logout no servidor antes de limpar o localStorage
    fetch('/logout')
        .then(() => {
            localStorage.removeItem('usuario_logado');
            localStorage.removeItem('usuario_id');
            localStorage.removeItem('usuario_nome');
            localStorage.removeItem('nivel_acesso');
            
            // Redirecionar para a página de login
            window.location.href = '/login';
        })
        .catch(error => {
            console.error('Erro ao fazer logout:', error);
            // Mesmo se ocorrer um erro, tente fazer logout do cliente
            localStorage.removeItem('usuario_logado');
            localStorage.removeItem('usuario_id');
            localStorage.removeItem('usuario_nome');
            localStorage.removeItem('nivel_acesso');
            window.location.href = '/login';
        });
}