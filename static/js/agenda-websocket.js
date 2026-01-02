/**
 * ============================================================
 * AGENDA WEBSOCKET - Sincronização Simples e Funcional
 * ============================================================
 * Recarrega agenda automaticamente quando recebe alterações
 * ============================================================
 */

const AgendaWebSocket = (() => {
    let socket = null;
    let usuarioAtual = null;
    let pingInterval = null;
    let notificationQueue = [];
    let lastNotificationTime = 0;

    const CONFIG = {
        PING_INTERVAL: 30000,
        RECONNECT_DELAY: 3000
    };
    
    /**
     * Log de debug
     */
    function log(mensagem, dados = null) {
        console.log(`[AgendaWS] ${mensagem}`, dados || '');
    }
    
    /**
     * Conectar ao WebSocket
     */
    function conectar() {
        try {
            log('🔌 Conectando ao WebSocket...');
            
            socket = io({
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionDelay: CONFIG.RECONNECT_DELAY
            });
            
            registrarEventos();
            
        } catch (error) {
            console.error('[AgendaWS] ❌ Erro ao conectar:', error);
            atualizarIndicador(false);
        }
    }
    
    /**
     * Registrar eventos do Socket
     */
    function registrarEventos() {
        // Conectado
        socket.on('connect', () => {
            log('✅ Conectado ao WebSocket');
            atualizarIndicador(true);
            iniciarPing();
        });
        
        // Desconectado
        socket.on('disconnect', (reason) => {
            log('❌ Desconectado:', reason);
            atualizarIndicador(false);
            pararPing();
        });
        
        // Erro
        socket.on('connect_error', (error) => {
            console.error('[AgendaWS] ❌ Erro:', error.message);
        });
        
        // ALTERAÇÃO RECEBIDA - PRINCIPAL!
        socket.on('alteracao_agenda', (dados) => {
            log('📡 Alteração recebida:', dados);
            processarAlteracao(dados);
        });
        
        // Usuário conectou
        socket.on('usuario_conectou', (data) => {
            log('👤 Usuário conectou:', data.usuario);
        });
        
        // Pong
        socket.on('pong', () => {
            // Silencioso
        });
    }
    
    /**
     * Processar alteração recebida
     */
    function processarAlteracao(dados) {
        const { tipo, entidade, usuario } = dados;
        
        // Verificar se é o próprio usuário
        const ehProprioUsuario = (usuario === usuarioAtual);

        // Mostrar notificação APENAS para outros usuários
        if (!ehProprioUsuario) {
            let mensagem = '';
            if (entidade === 'DEMANDA') {
                if (tipo === 'INSERT') {
                    mensagem = `${usuario} criou uma demanda`;
                } else if (tipo === 'UPDATE') {
                    mensagem = `${usuario} atualizou uma demanda`;
                } else if (tipo === 'DELETE') {
                    mensagem = `${usuario} excluiu uma demanda`;
                }
            } else if (entidade === 'DIARIA_TERCEIRIZADO') {
                mensagem = `${usuario} atualizou uma diária`;
            } else if (entidade === 'LOCACAO_FORNECEDOR') {
                mensagem = `${usuario} criou uma locação`;
            }
            
            if (mensagem) {
                mostrarNotificacao(mensagem);
            }
        }
        


        // if (ehProprioUsuario) {
        //     log('⏭️ Própria alteração - atualizando sem notificação');
        // } else {
        //     // Mostrar notificação APENAS para outros usuários
        //     let mensagem = '';
        //     if (entidade === 'DEMANDA') {
        //         if (tipo === 'INSERT') {
        //             mensagem = `${usuario} criou uma demanda`;
        //         } else if (tipo === 'UPDATE') {
        //             mensagem = `${usuario} atualizou uma demanda`;
        //         } else if (tipo === 'DELETE') {
        //             mensagem = `${usuario} excluiu uma demanda`;
        //         }
        //     } else if (entidade === 'DIARIA_TERCEIRIZADO') {
        //         mensagem = `${usuario} atualizou uma diária`;
        //     } else if (entidade === 'LOCACAO_FORNECEDOR') {
        //         mensagem = `${usuario} atualizou uma locação`;
        //     }
            
        //     if (mensagem) {
        //         mostrarNotificacao(mensagem);
        //     }
        // }


        // RECARREGAR AGENDA AUTOMATICAMENTE (sempre)
        log('🔄 Recarregando agenda...');
        recarregarAgenda();
    }
    
    /**
     * Recarrega agenda completa (SOLUÇÃO SIMPLES)
     */
    async function recarregarAgenda() {
        try {
            // Verificar se função existe
            if (typeof window.carregarDadosAgenda !== 'function') {
                log('⚠️ Função carregarDadosAgenda() não existe - usando fetch direto');
                await recarregarAgendaDireto();
                return;
            }
            
            // Salvar scroll
            const scrollPos = window.pageYOffset;
            
            // Recarregar dados
            await window.carregarDadosAgenda();
            
            // Renderizar
            if (typeof window.renderizarAgenda === 'function') {
                window.renderizarAgenda();
            }
            
            // Restaurar scroll
            window.scrollTo(0, scrollPos);
            
            // Flash visual
            setTimeout(() => {
                const celulas = document.querySelectorAll('.agenda-table td[onclick]');
                celulas.forEach(c => {
                    c.style.transition = 'background-color 0.6s';
                    const corOriginal = c.style.backgroundColor;
                    c.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
                    setTimeout(() => {
                        c.style.backgroundColor = corOriginal;
                    }, 600);
                });
            }, 100);
            
            log('✅ Agenda recarregada!');
            
        } catch (error) {
            console.error('[AgendaWS] ❌ Erro ao recarregar:', error);
        }
    }
    
    /**
     * Recarrega agenda fazendo fetch direto
     */
    async function recarregarAgendaDireto() {
        try {
            // Verificar se tem semanas
            if (!window.semanas || !window.semanaAtual === undefined) {
                log('⚠️ Variáveis semanas/semanaAtual não existem');
                return;
            }
            
            const semana = window.semanas[window.semanaAtual];
            if (!semana) {
                log('⚠️ Semana atual não encontrada');
                return;
            }
            
            // Salvar scroll
            const scrollPos = window.pageYOffset;
            
            // Fetch dados
            const response = await fetch(`/api/agenda/dados?inicio=${semana.inicio}&fim=${semana.fim}`);
            if (!response.ok) {
                throw new Error('Erro ao buscar dados');
            }
            
            const dados = await response.json();
            
            // Atualizar variáveis globais
            window.dadosAgenda = dados;
            window.demandas = dados.demandas || [];
            window.diarias_terceirizados = dados.diarias_terceirizados || [];
            
            // Renderizar
            if (typeof window.renderizarAgenda === 'function') {
                window.renderizarAgenda();
            }
            
            // Restaurar scroll
            window.scrollTo(0, scrollPos);
            
            log('✅ Agenda recarregada (método direto)');
            
        } catch (error) {
            console.error('[AgendaWS] ❌ Erro no reload direto:', error);
        }
    }
    
    /**
     * Ping periódico
     */
    function iniciarPing() {
        pararPing();
        pingInterval = setInterval(() => {
            if (socket && socket.connected) {
                socket.emit('ping');
            }
        }, CONFIG.PING_INTERVAL);
    }
    
    function pararPing() {
        if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
        }
    }
    
    /**
     * Indicador visual de conexão
     */
    function atualizarIndicador(conectado) {
        let ind = document.getElementById('ws-status');
        
        if (!ind) {
            ind = document.createElement('div');
            ind.id = 'ws-status';
            ind.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                z-index: 10000;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                transition: background-color 0.3s;
            `;
            document.body.appendChild(ind);
        }
        
        ind.style.backgroundColor = conectado ? '#10b981' : '#ef4444';
        ind.title = conectado ? '✅ WebSocket conectado' : '❌ Desconectado';
    }
    
    /**
     * Notificação toast
     */
    function mostrarNotificacao(mensagem) {
        // Debounce: ignorar se notificação igual foi enviada há menos de 1s
        const agora = Date.now();
        const notifExistente = notificationQueue.find(n => 
            n.mensagem === mensagem && (agora - n.timestamp) < 1000
        );
        
        if (notifExistente) {
            log('🚫 Notificação duplicada ignorada:', mensagem);
            return;
        }
        
        // Adicionar à fila
        notificationQueue.push({ mensagem, timestamp: agora });
        
        // Limpar fila antiga (manter últimos 5 segundos)
        notificationQueue = notificationQueue.filter(n => 
            (agora - n.timestamp) < 5000
        );
        
        let container = document.getElementById('ws-notif');
        
        if (!container) {
            container = document.createElement('div');
            container.id = 'ws-notif';
            container.style.cssText = `
                position: fixed;
                top: 80px;
                right: 20px;
                z-index: 9999;
                max-width: 350px;
            `;
            document.body.appendChild(container);
        }
        
        const notif = document.createElement('div');
        notif.style.cssText = `
            background: rgba(80, 80, 80, 0.9);
            color: white;
            border-left: 4px solid rgba(255, 255, 255, 0.3);
            padding: 12px 16px;
            margin-bottom: 10px;
            border-radius: 4px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            animation: slideIn 0.3s ease-out;
            font-size: 14px;
            backdrop-filter: blur(10px);
        `;
        
        notif.innerHTML = `
            <span style="margin-right: 8px;">📡</span>
            <span>${mensagem}</span>
        `;
        
        container.appendChild(notif);
        
        setTimeout(() => {
            notif.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => notif.remove(), 300);
        }, 2500);
    }
    
    // API Pública
    return {
        init(usuario) {
            log('🚀 Inicializando...');
            usuarioAtual = usuario;
            
            if (typeof io === 'undefined') {
                console.error('[AgendaWS] ❌ Socket.IO não carregado!');
                return false;
            }
            
            conectar();
            injectarEstilos();
            return true;
        },
        
        isConnected() {
            return socket && socket.connected;
        },
        
        desconectar() {
            pararPing();
            if (socket) {
                socket.disconnect();
            }
        }
    };
})();

// Injetar estilos de animação
function injectarEstilos() {
    if (document.getElementById('ws-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'ws-styles';
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(400px); opacity: 0; }
        }
    `;
    document.head.appendChild(style);
}

console.log('[AgendaWS] 📦 Módulo carregado');