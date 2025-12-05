/**
 * Sistema genérico de controle de acesso
 * Uso: incluir este arquivo em todas as páginas que precisam de controle
 */

const ControleAcesso = {
    nivelAcesso: null,
    acessoLeitura: false,
    
    /**
     * Inicializa o controle de acesso
     * @param {string} nivel - Nível de acesso ('E', 'L', 'N')
     */
    inicializar: function(nivel) {
        this.nivelAcesso = nivel;
        this.acessoLeitura = nivel === 'L';
        
        if (this.acessoLeitura) {
            this.aplicarModoLeitura();
        }
        
        console.log('Controle de acesso inicializado:', nivel);
    },
    
    /**
     * Aplica restrições de modo leitura
     */
    aplicarModoLeitura: function() {
        // Desabilitar botões de novo/criar
        this.desabilitarBotoes([
            'btnNovoRegistro',
            'btnNovoRegistroFooter',
            'btnNovo',
            'btnCriar',
            'btnAdicionar'
        ]);
        
        // Desabilitar botões de salvar
        this.desabilitarBotoes([
            'btnSalvar',
            'btnSalvarVeiculo',
            'btnSalvarMotorista',
            'btnGravar'
        ]);
        
        // Desabilitar botões de exclusão
        this.desabilitarBotoes([
            'btnExcluir',
            'btnDeletar',
            'btnRemover'
        ], 'btnExcluir');
        
        // Bloquear cliques em botões de editar
        this.bloquearEdicao();
        
        // Adicionar badge visual
        this.adicionarBadgeLeitura();
        
        // Adicionar classe ao body
        $('body').addClass('modo-leitura-ativo');
    },
    
    /**
     * Desabilita botões por ID ou classe
     */
    desabilitarBotoes: function(ids, classeAdicional = '') {
        ids.forEach(id => {
            $(`#${id}, .${id}`).prop('disabled', true)
                .addClass('disabled')
                .attr('title', 'Você não tem permissão para esta ação');
        });
    },
    
    /**
     * Bloqueia ações de edição
     */
    bloquearEdicao: function() {
        const self = this;
        
        // Bloquear botões de editar
        $(document).on('click', '.btnEditar, .btn-editar, [data-action="editar"]', function(e) {
            if (self.acessoLeitura) {
                e.preventDefault();
                e.stopPropagation();
                alert('Você possui apenas permissão de leitura. Não é possível editar registros.');
                return false;
            }
        });
        
        // Bloquear exclusão
        $(document).on('click', '.btnExcluir, .btn-excluir, [data-action="excluir"]', function(e) {
            if (self.acessoLeitura) {
                e.preventDefault();
                e.stopPropagation();
                alert('Você possui apenas permissão de leitura. Não é possível excluir registros.');
                return false;
            }
        });
    },
    
    /**
     * Adiciona badge visual de modo leitura
     */
    adicionarBadgeLeitura: function() {
        const badge = '<span class="badge bg-warning text-dark ms-2" id="badgeModoLeitura">' +
                     '<i class="fas fa-eye"></i> Modo Leitura</span>';
        
        // Tenta adicionar em diferentes locais comuns
        if ($('.header-section h2').length) {
            $('.header-section h2').append(badge);
        } else if ($('h1').first().length) {
            $('h1').first().append(badge);
        } else if ($('h2').first().length) {
            $('h2').first().append(badge);
        }
    },
    
    /**
     * Verifica se pode executar ação
     */
    podeExecutar: function(mostrarAlerta = true) {
        if (this.acessoLeitura) {
            if (mostrarAlerta) {
                alert('Você não tem permissão para executar esta ação.');
            }
            return false;
        }
        return true;
    }
};

// CSS para modo leitura (adicionar ao head via JavaScript)
$(document).ready(function() {
    if (!$('#estiloModoLeitura').length) {
        $('head').append(`
            <style id="estiloModoLeitura">
                .modo-leitura-ativo .disabled {
                    opacity: 0.6;
                    cursor: not-allowed !important;
                }
                .modo-leitura-ativo .btn-success.disabled,
                .modo-leitura-ativo .btn-primary.disabled {
                    background-color: #6c757d !important;
                    border-color: #6c757d !important;
                }
                #badgeModoLeitura {
                    animation: pulse 2s infinite;
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.7; }
                }
            </style>
        `);
    }
});
