import pytesseract
import cv2
import re
import pandas as pd
import os

# Caminho do tesseract no Windows
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def preprocessar_imagem(caminho_imagem):
    """Melhora contraste e binariza a imagem para OCR."""
    imagem = cv2.imread(caminho_imagem)
    imagem = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    imagem = cv2.GaussianBlur(imagem, (1, 1), 0)
    _, imagem_bin = cv2.threshold(imagem, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return imagem_bin

def ocr_linha_a_linha(imagem_pre):
    """Executa OCR linha a linha com layout simples."""
    texto = pytesseract.image_to_string(imagem_pre, lang='por', config='--psm 6')
    return texto

def limpar_linhas(texto):
    """Remove linhas vazias ou desnecessárias."""
    return [linha.strip() for linha in texto.split('\n') if linha.strip()]

def extrair_dados(linhas):
    """
    Extrai dados de cada item baseado em regex com estrutura:
    [item] [código] [descrição...] [qtde] [unidade] [unitário] [total]
    """
    padrao = re.compile(r'^(\d{3})\s+(\d{13})\s+(.+?)\s+(\d+,\d{2})\s+(\d+,\d{2})$')
    itens = []

    for linha in linhas:
        match = padrao.match(linha)
        if match:
            itens.append({
                'item': match.group(1),
                'codigo': match.group(2),
                'descricao': match.group(3),
                'preco_unitario': float(match.group(4).replace(',', '.')),
                'preco_total': float(match.group(5).replace(',', '.')),
            })
    return pd.DataFrame(itens)

def preprocessar_imagem_melhorado(caminho_imagem):
    """Melhora contraste, remove ruído e binariza a imagem para OCR (versão melhorada)."""
    imagem_original = cv2.imread(caminho_imagem)
    imagem_cinza = cv2.cvtColor(imagem_original, cv2.COLOR_BGR2GRAY)

    # 1. Ajuste de Contraste (Equalização Adaptativa do Histograma)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    imagem_contraste = clahe.apply(imagem_cinza)

    # 2. Remoção de Ruído 
    imagem_suavizada = cv2.GaussianBlur(imagem_contraste, (6, 6), 0)

    # 3. Binarização Adaptativa 
    imagem_bin = cv2.adaptiveThreshold(imagem_suavizada, 300, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 11, 2) # THRESH_BINARY_INV pode ajudar em alguns casos

    return imagem_bin

def parse_receipt_text(texto_ocr: str) -> pd.DataFrame:
    padrao_item = re.compile(
        r"""
        (?P<item>\d{3})           # número do item
        \s+
        (?P<ean>\d{8,14})         # EAN (código de barras, 8 a 14 dígitos)
        \s+
        (?P<descricao>.+?)       # descrição do produto (lazy match)
        \n
        (?P<quantidade>\d+,\d{3})   # quantidade no formato 1,000
        \s+
        (?P<unidade>\w{2})         # unidade (2 letras, ex: PC, Un)
        \s+x\s+
        (?P<preco_unitario>\d+,\d{2}) # preço unitário (ex: 10,83)
        \s+
        (?P<preco_total>\d+,\d{2})   # preço total (ex: 10,89)
        """, re.VERBOSE | re.MULTILINE
    )

    registros = []

    for match in padrao_item.finditer(texto_ocr):
        grupo = match.groupdict()

        # Limpeza e conversão de tipos
        grupo['quantidade'] = float(grupo['quantidade'].replace(',', '.'))
        grupo['preco_unitario'] = float(grupo['preco_unitario'].replace(',', '.'))
        grupo['preco_total'] = float(grupo['preco_total'].replace(',', '.'))
        registros.append(grupo)

    df = pd.DataFrame(registros)
    return df

def parse_receipt_text_list(linhas):
    """
    Recebe uma lista de linhas do cupom e retorna um DataFrame com os dados estruturados.
    """
    itens = []
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        match_item = re.match(r'^(\d{3})\s+(\d{13})\s+(.+)$', linha)
        if match_item:
            codigo_item = match_item.group(1)
            ean = match_item.group(2)
            descricao = match_item.group(3).strip()

            # próxima linha: quantidade, unidade, preço unitário e total
            if i + 1 < len(linhas):
                linha_valores = linhas[i + 1]
                match_valores = re.match(r'^([\d,\.]+)\s+(\w+)\s+x\s+([\d,\.]+)\s+([\d,\.]+)', linha_valores)
                if match_valores:
                    quantidade = match_valores.group(1).replace(',', '.')
                    unidade = match_valores.group(2)
                    preco_unitario = match_valores.group(3).replace(',', '.')
                    preco_total = match_valores.group(4).replace(',', '.')

                    itens.append({
                        'item': codigo_item,
                        'ean': ean,
                        'descricao': descricao,
                        'quantidade': float(quantidade),
                        'unidade': unidade,
                        'preco_unitario': float(preco_unitario),
                        'preco_total': float(preco_total)
                    })
                    i += 2
                    continue
        i += 1

    return pd.DataFrame(itens)

def parse_receipt_text_list_2(linhas):
    """
    Extrai os itens válidos de uma lista de linhas OCR de cupom fiscal e retorna um DataFrame.
    Ignora linhas de desconto e ruído.
    """
    itens = []
    i = 0

    while i < len(linhas):
        linha = linhas[i]

        # Tenta casar linha com item + ean + descrição
        match_item = re.match(r'^(\d{3})\s+(\d{8,14})\s+(.+)$', linha)
        if match_item:
            codigo_item = match_item.group(1)
            ean = match_item.group(2)
            descricao = match_item.group(3).strip()

            # Verifica se a próxima linha contém os valores numéricos esperados
            if i + 1 < len(linhas):
                linha_valores = linhas[i + 1].strip()

                # Casar com o padrão de quantidade, unidade, x, preco_unitario, preco_total
                match_valores = re.match(
                    r'^([\d.,]+)\s+(\w+)\s+x\s+([\d.,]+)\s+([\d.,]+)', linha_valores
                )

                if match_valores:
                    try:
                        quantidade = float(match_valores.group(1).replace(',', '.'))
                        unidade = match_valores.group(2)
                        preco_unitario = float(match_valores.group(3).replace(',', '.'))
                        preco_total = float(match_valores.group(4).replace(',', '.'))

                        itens.append({
                            'item': codigo_item,
                            'ean': ean,
                            'descricao': descricao,
                            'quantidade': quantidade,
                            'unidade': unidade,
                            'preco_unitario': preco_unitario,
                            'preco_total': preco_total
                        })
                        i += 2  # pula para a próxima dupla de linhas
                        continue
                    except:
                        pass  # Se falhar a conversão, ignora e tenta próxima linha
        i += 1  # Avança normalmente caso não encontre item válido

    return pd.DataFrame(itens)

def parse_receipt_text_list_3(linhas):
    """
    Recebe uma lista de linhas do cupom e retorna um DataFrame com os dados estruturados.
    Torna o parser mais robusto contra variações de OCR e erros de formatação.
    """
    itens = []
    i = 0
    while i < len(linhas):
        linha = linhas[i]

        # Match do item + EAN + descrição
        match_item = re.match(r'^(\d{3})\s+([\d\(\):;]{8,14})\s+(.+)', linha)
        if match_item:
            codigo_item = match_item.group(1)
            ean = re.sub(r'\D', '', match_item.group(2))  # remove tudo que não é dígito
            descricao = match_item.group(3).strip()

            if i + 1 < len(linhas):
                linha_valores = linhas[i + 1]

                # Match linha de quantidade, unidade, preço unitário e total
                match_valores = re.search(
                    r'([\d,.]+)\s+(\w+)\s+[xX×]\s+([\d,.]+)\s+([\d,.]+)', linha_valores
                )
                if match_valores:
                    quantidade_raw = match_valores.group(1).replace('.', '').replace(',', '.')
                    unidade = match_valores.group(2)
                    preco_unitario_raw = match_valores.group(3).replace('.', '').replace(',', '.')
                    preco_total_raw = match_valores.group(4).replace('.', '').replace(',', '.')

                    try:
                        quantidade = float(quantidade_raw)
                        preco_unitario = float(preco_unitario_raw)
                        preco_total = float(preco_total_raw)

                        itens.append({
                            'item': codigo_item,
                            'ean': ean,
                            'descricao': descricao,
                            'quantidade': quantidade,
                            'unidade': unidade,
                            'preco_unitario': preco_unitario,
                            'preco_total': preco_total
                        })
                        i += 2
                        continue
                    except ValueError:
                        pass  # ignora linha inválida se falhar conversão numérica

        i += 1

    return pd.DataFrame(itens)

def parse_receipt_text_list_4(linhas):
    import re
    itens = []
    i = 0

    while i < len(linhas):
        linha = linhas[i]

        # Tenta identificar linha com item + EAN + descrição
        match_item = re.match(r'^(\d{3})\s+([\d\(\):;]{8,14})\s+(.+)', linha)
        if match_item:
            codigo_item = match_item.group(1)
            ean = re.sub(r'\D', '', match_item.group(2))  # remove tudo que não for número
            descricao = match_item.group(3).strip()

            if i + 1 < len(linhas):
                linha_valores = linhas[i + 1]

                # Regex mais flexível para linha de preços
                match_valores = re.search(
                    r'([\d.,]+)\s+([A-Za-z]{1,3})\s+[\sxX×]{0,2}\s*([\d.,]+)\s+([\d.,]+)',
                    linha_valores
                )
                if match_valores:
                    qtd_raw = match_valores.group(1).replace('.', '').replace(',', '.')
                    unidade = match_valores.group(2)
                    preco_unitario_raw = match_valores.group(3).replace('.', '').replace(',', '.')
                    preco_total_raw = match_valores.group(4).replace('.', '').replace(',', '.')

                    try:
                        quantidade = float(qtd_raw)
                        preco_unitario = float(preco_unitario_raw)
                        preco_total = float(preco_total_raw)

                        itens.append({
                            'item': codigo_item,
                            'ean': ean,
                            'descricao': descricao,
                            'quantidade': quantidade,
                            'unidade': unidade,
                            'preco_unitario': preco_unitario,
                            'preco_total': preco_total
                        })

                        i += 2
                        continue
                    except ValueError:
                        pass  # ignora conversão inválida

        i += 1

    return pd.DataFrame(itens)

def parse_receipt_text_list_5(linhas):
    """
    Lista de linhas OCR, retornando um DataFrame.
    """
    itens_data = []
    # Procurar especificamente pelas linhas do item 2
    for i, linha in enumerate(linhas):
        if re.match(r'^002\s+', linha):
            codigo_item_match = re.match(r'^(\d{3})\s+([\d\(\):;]{8,14})\s+(.+)', linha)
            if codigo_item_match:
                codigo_item = codigo_item_match.group(1)
                ean = re.sub(r'\D', '', codigo_item_match.group(2))
                descricao = codigo_item_match.group(3).strip()

                if i + 1 < len(linhas):
                    linha_valores = linhas[i + 1]
                    match_valores = re.search(
                        r'([\d.,]+)\s+([A-Za-z]{1,3})\s+[\sxX×]{0,2}\s*([\d.,]+)\s+([\d.,]+)',
                        linha_valores
                    )
                    if match_valores:
                        try:
                            qtd_raw = match_valores.group(1).replace('.', '').replace(',', '.')
                            unidade = match_valores.group(2)
                            preco_unitario_raw = match_valores.group(3).replace('.', '').replace(',', '.')
                            preco_total_raw = match_valores.group(4).replace('.', '').replace(',', '.')

                            quantidade = float(qtd_raw)
                            preco_unitario = float(preco_unitario_raw)
                            preco_total = float(preco_total_raw)

                            itens_data.append({
                                'item': codigo_item,
                                'ean': ean,
                                'descricao': descricao,
                                'quantidade': quantidade,
                                'unidade': unidade,
                                'preco_unitario': preco_unitario,
                                'preco_total': preco_total
                            })
                            break # Encontrou o item 2 e seus dados, pode parar
                        except ValueError:
                                print(f"Erro de conversão de valor na linha: {linha_valores}")
                            
        elif re.search(r'ARR CAMIL LF T1 Ska', linha, re.IGNORECASE):
            # O item '002' não foi capturado
            partes = re.split(r'\s+', linha.strip(), maxsplit=4) # Tentativa de dividir a linha
            if len(partes) >= 4:
                descricao = " ".join(partes[2:])
                # Tentar encontrar a linha de valores na próxima linha
                if i + 1 < len(linhas):
                    linha_valores = linhas[i + 1]
                    match_valores = re.search(
                        r'([\d.,]+)\s+([A-Za-z]{1,3})\s+[\sxX×]{0,2}\s*([\d.,]+)\s+([\d.,]+)',
                        linha_valores
                    )
                    if match_valores:
                        try:
                            qtd_raw = match_valores.group(1).replace('.', '').replace(',', '.')
                            unidade = match_valores.group(2)
                            preco_unitario_raw = match_valores.group(3).replace('.', '').replace(',', '.')
                            preco_total_raw = match_valores.group(4).replace('.', '').replace(',', '.')

                            quantidade = float(qtd_raw)
                            preco_unitario = float(preco_unitario_raw)
                            preco_total = float(preco_total_raw)

                            # Tentar inferir o item e ean 
                            itens_data.append({
                                'item': '002', 
                                'ean': '',    
                                'descricao': descricao,
                                'quantidade': quantidade,
                                'unidade': unidade,
                                'preco_unitario': preco_unitario,
                                'preco_total': preco_total
                            })
                            break
                        except ValueError:
                            pass

    return pd.DataFrame(itens_data)

def preprocessar_imagem_v2(caminho_imagem):
    """Melhora contraste e binariza a imagem para OCR."""
    imagem = cv2.imread(caminho_imagem)
    imagem = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    imagem = cv2.GaussianBlur(imagem, (1, 1), 0)
    _, imagem_bin = cv2.threshold(imagem, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return imagem_bin

def ocr_linha_a_linha_v2(imagem_pre):
    """Executa OCR linha a linha com layout simples."""
    texto = pytesseract.image_to_string(imagem_pre, lang='por', config='--psm 6')
    return texto

def limpar_linhas_v2(texto):
    """Remove linhas vazias ou desnecessárias."""
    return [linha.strip() for linha in texto.split('\n') if linha.strip()]

def processar_pasta_de_imagens(pasta_imagens):
    """
    Processa todas as imagens .jpg em uma pasta, extrai os dados e retorna um DataFrame consolidado.
    """
    all_dfs = []
    for nome_arquivo in os.listdir(pasta_imagens):
        if nome_arquivo.lower().endswith(".jpg"):
            caminho_completo = os.path.join(pasta_imagens, nome_arquivo)
            print(f"Processando imagem: {nome_arquivo}")
            try:
                imagem = preprocessar_imagem(caminho_completo)
                texto = ocr_linha_a_linha(imagem)
                linhas = limpar_linhas(texto)
                df_imagem = extrair_varios_padroes(linhas)
                if not df_imagem.empty:
                    df_imagem['nome_arquivo'] = nome_arquivo # Adiciona o nome do arquivo como identificador
                    all_dfs.append(df_imagem)
            except Exception as e:
                print(f"Erro ao processar {nome_arquivo}: {e}")

    df_consolidado = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    return df_consolidado

def extrair_varios_padroes(texto):
    dfs = []

    # Primeira extração (padrão já conhecido)
    dfs.append(parse_receipt_text_list(texto))
    dfs.append(parse_receipt_text_list_2(texto))
    dfs.append(parse_receipt_text_list_3(texto))
    dfs.append(parse_receipt_text_list_4(texto))
    dfs.append(parse_receipt_text_list_5(texto))
    
    df_final = pd.concat(dfs, ignore_index=True)

    # Remover duplicados por item ou EAN
    df_final = df_final.drop_duplicates(subset=['item'])

    return df_final

def extrair_varios_padroes_v2(linhas):
    """
    Aplica várias funções de extração (que você já definiu) e concatena os resultados.
    """
    dfs = []
    df1 = parse_receipt_text_list(linhas)
    if not df1.empty:
        dfs.append(df1)
    df2 = parse_receipt_text_list_2(linhas)
    if not df2.empty:
        dfs.append(df2)
    df3 = parse_receipt_text_list_3(linhas)
    if not df3.empty:
        dfs.append(df3)
    df4 = parse_receipt_text_list_4(linhas)
    if not df4.empty:
        dfs.append(df4)
    df_final = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    df_final = df_final.drop_duplicates(subset=['item'])
    return df_final