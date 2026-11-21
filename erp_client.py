def consultar_valores_e_agenda(especialidade: str, medico_preferencia: str = None) -> dict:
    """
    Simula a consulta ao ERP. Futuramente aqui entra a chamada HTTP/SQL do ERP da clínica.
    """
    tabela_mock = {
        "cardiologia": {
            "medico": "Dr. Henrique Mendes",
            "valor": 380.00,
            "horarios_livres": ["Amanhã às 10:00", "Amanhã às 15:30", "Quinta-feira às 09:00"]
        },
        "dermatologia": {
            "medico": "Dra. Camila Rocha",
            "valor": 350.00,
            "horarios_livres": ["Amanhã às 14:00", "Quarta-feira às 11:00", "Sexta-feira às 16:00"]
        },
        "clinica geral": {
            "medico": "Dr. Rafael Costa",
            "valor": 220.00,
            "horarios_livres": ["Hoje às 17:00", "Amanhã às 08:30", "Amanhã às 11:30"]
        }
    }

    chave = especialidade.lower().strip()
    for esp, dados in tabela_mock.items():
        if esp in chave or chave in esp:
            return {
                "encontrado": True,
                "especialidade": esp.title(),
                "medico": medico_preferencia or dados["medico"],
                "valor_consulta": dados["valor"],
                "horarios_disponiveis": dados["horarios_livres"]
            }

    return {
        "encontrado": False,
        "mensagem": "Especialidade não localizada automaticamente. Verifique na base de conhecimento ou consulte a recepção."
    }
