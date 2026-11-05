"""Painel do Rodada Pronta (abre no navegador). Inicie pelo arquivo Iniciar.bat."""

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import rodada_pronta as cr

BASE = Path(__file__).resolve().parent
SAIDA = BASE / "saida"
IMAGENS = [   # (início do nome do arquivo, rótulo)
    ("agenda", "Agenda"),
    ("destaque", "Jogo da rodada"),
    ("resultados", "Resultados"),
    ("classificacao", "Classificação"),
    ("chaveamento", "Mata-mata"),
    ("gols", "Artilheiros"),
    ("assistencias", "Assistências"),
    ("defesas", "Goleiros"),
    ("notas", "Notas médias"),
    ("f2_stats", "Estatísticas Individuais"),
]
STATS_INDIVIDUAIS = ("gols", "assistencias", "defesas", "notas")
ZONAS_FORM = [("cl", "Champions League"), ("el", "Europa League"),
              ("ecl", "Conference League"), ("rel", "Rebaixamento")]

st.set_page_config(page_title="Rodada Pronta", page_icon="⚽", layout="wide")
# o painel só LÊ os escudos já baixados; quem baixa é o gerador
cr._escudos_so_cache = True


# ------------------------------------------------------------------ utilidades
def ultima_rodada(slug):
    """{'rodada': 10, 'pasta': 'rodada_10', 'chave': '10||'} da última geração."""
    f = SAIDA / slug / "ultima.json"
    if f.exists():
        try:
            dados = json.loads(f.read_text(encoding="utf-8"))
            dados.setdefault("pasta", f"rodada_{dados['rodada']}")
            dados.setdefault("chave", f"{dados['rodada']}||")
            return dados
        except Exception:  # noqa
            return None
    return None


def listar_imagens(pasta):
    """Arquivos de imagem da rodada, em ordem, com o rótulo da aba."""
    achados = []
    for inicio, nome in IMAGENS:
        if inicio in STATS_INDIVIDUAIS and not cr.GERAR_STATS_INDIVIDUAIS:
            continue        # parâmetro GERAR_STATS_INDIVIDUAIS (rodada_pronta.py)
        arquivos = sorted(pasta.glob(f"{inicio}*.png"))
        for arq in arquivos:
            m = re.search(r"_(\d+)\.png$", arq.name)
            if m and inicio == "f2_stats":      # ex.: Estatísticas Individuais 1/2
                rotulo = f"{nome} {m.group(1)}/{len(arquivos)}"
            else:
                rotulo = nome + (f" {m.group(1)}" if m else "")
            achados.append((arq.name, rotulo))
    return achados


def bloco_resultados(slug, ultima, pasta, arq, rodada):
    """Botão 'Atualizar Resultados' (busca os placares e refaz só a imagem de
    resultados) e a legenda da última atualização."""
    if st.button("🔄 Atualizar Resultados",
                 key=f"atualizar_res_{slug}_{rodada}_{arq}",
                 help="Busca os placares no Sofascore e refaz a imagem de "
                      "resultados desta rodada. Use quantas vezes quiser "
                      "enquanto os jogos acontecem."):
        with st.spinner("Buscando os resultados..."):
            codigo, dados, log = executar_resultados(
                slug, None, (ultima or {}).get("chave"))
        if codigo == 0 and dados:
            st.rerun()
        ultimas = [l for l in log.splitlines() if l.strip()]
        st.error("Não consegui buscar os resultados agora. Tente de novo em "
                 "instantes.")
        st.code("\n".join(ultimas[-5:]), language=None)
    try:
        meta = json.loads(
            (pasta / "resultados.json").read_text(encoding="utf-8"))
        partes = []
        if meta.get("jogos"):
            enc = sum(1 for j in meta["jogos"] if j.get("situacao") == "final")
            partes.append(f"{enc} de {len(meta['jogos'])} jogos encerrados")
        if meta.get("atualizado"):
            partes.append("atualizado em " + datetime.fromisoformat(
                meta["atualizado"]).strftime("%d/%m às %H:%M"))
        if partes:
            st.caption(" • ".join(partes))
    except Exception:  # noqa
        pass


def _rodar(cmd, timeout):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"Tempo esgotado (mais de {timeout // 60} minutos)."
    log = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    return r.returncode, log


def executar(slug, rodada, chave, imagens, site):
    cmd = [sys.executable, str(BASE / "rodada_pronta.py"),
           "--competicao", slug]
    if chave:
        cmd += ["--rodada-chave", chave]
    elif rodada:
        cmd.append(f"--{rodada}")
    if not imagens:
        cmd.append("--sem-imagens")
    if not site:
        cmd.append("--sem-site")
    return _rodar(cmd, 900)


def executar_resultados(slug, rodada, chave):
    """Busca os placares da rodada e gera a(s) imagem(ns) de resultados.
    Sem rodada escolhida, usa a do último tópico gerado.
    Devolve (código, dados, log)."""
    cmd = [sys.executable, str(BASE / "rodada_pronta.py"),
           "--competicao", slug, "--resultados"]
    if chave:
        cmd += ["--rodada-chave", chave]
    elif rodada:
        cmd.append(f"--{rodada}")
    codigo, log = _rodar(cmd, 300)
    dados = None
    for linha in log.splitlines():
        if linha.startswith("JSON:"):
            try:
                dados = json.loads(linha[5:])
            except ValueError:
                pass
    return codigo, dados, log


def buscar_link(url):
    """Consulta o Sofascore (em outro processo) e devolve (dados, log)."""
    codigo, log = _rodar([sys.executable, str(BASE / "rodada_pronta.py"),
                          "--info-link", url], 240)
    for linha in log.splitlines():
        if linha.startswith("JSON:"):
            return json.loads(linha[5:]), log
    return None, log


def buscar_nomes(slug):
    """Lista os times e estádios da competição (em outro processo)."""
    codigo, log = _rodar([sys.executable, str(BASE / "rodada_pronta.py"),
                          "--competicao", slug, "--listar-nomes"], 300)
    for linha in log.splitlines():
        if linha.startswith("JSON:"):
            return json.loads(linha[5:]), log
    return None, log


def _hex(v, padrao):
    v = (v or "").strip()
    return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else padrao


def _pares_para_texto(d):
    return "\n".join(f"{a} = {b}" for a, b in (d or {}).items())


def _texto_para_pares(texto):
    pares = {}
    for linha in (texto or "").splitlines():
        if "=" in linha:
            a, b = (x.strip() for x in linha.split("=", 1))
            if a and b:
                pares[a] = b
    return pares


def _tabela_nomes(titulo, descobertos, mapa, chave):
    """Painel de duas colunas: nome no Sofascore | nome que aparece nas
    imagens. Os ajustes valem para TODAS as competições. Devolve
    (alterados, revertidos): o que foi mudado e o que voltou ao original."""
    mapa = mapa or {}
    if descobertos:     # só os nomes desta competição (os outros ficam salvos)
        nomes = sorted(set(descobertos), key=str.lower)
    else:
        nomes = sorted(set(mapa), key=str.lower)
    st.markdown(f"**{titulo}** ({len(nomes)})")
    if not nomes:
        st.caption("Nenhum nome ainda. Use o botão \"Buscar times e estádios "
                   "no Sofascore\" acima do formulário.")
        return {}, []
    df = pd.DataFrame({"Nome no Sofascore": nomes,
                       "Nome nas imagens": [mapa.get(n, n) for n in nomes]})
    assinatura = hashlib.md5(
        "|".join(f"{n}={mapa.get(n, '')}" for n in nomes).encode("utf-8")
    ).hexdigest()[:8]
    editado = st.data_editor(
        df, hide_index=True, use_container_width=True,
        disabled=["Nome no Sofascore"], height=min(38 * len(nomes) + 40, 460),
        key=f"{chave}_{assinatura}")
    alterados, revertidos = {}, []
    for linha in editado.to_dict("records"):
        origem = str(linha["Nome no Sofascore"]).strip()
        novo = str(linha["Nome nas imagens"] or "").strip()
        if not origem:
            continue
        if novo and novo != origem:
            alterados[origem] = novo
        elif origem in mapa and mapa[origem] != origem:
            revertidos.append(origem)      # voltou ao nome original
    return alterados, revertidos


# ------------------------------------------------------------------ formulário
def formulario_competicao(prefixo, cfg, texto_botao):
    """Mostra os campos de uma competição. Retorna o cadastro novo ao enviar."""
    idiomas = list(cr.IDIOMAS)
    with st.form(f"form_{prefixo}"):
        nome = st.text_input(
            "Nome usado no título do tópico", cfg.get("nome", ""),
            key=f"{prefixo}_nome",
            help="Ex.: Série A Enilive  →  título: Série A Enilive 2026/27 - "
                 "10° Giornata")
        nome_curto = st.text_input(
            "Nome curto (subtítulo das imagens)",
            cfg.get("nome_curto") or cfg.get("nome", ""),
            key=f"{prefixo}_curto")
        c1, c2 = st.columns(2)
        tid = c1.number_input("ID da competição (Sofascore)", 0, 10**7,
                              int(cfg.get("tournament_id") or 0), 1,
                              key=f"{prefixo}_tid")
        sid = c2.number_input("ID da temporada", 0, 10**9,
                              int(cfg.get("season_id") or 0), 1,
                              key=f"{prefixo}_sid")
        auto = st.checkbox(
            "Detectar a temporada atual automaticamente a cada geração",
            bool(cfg.get("season_auto")), key=f"{prefixo}_auto")
        civil = st.checkbox(
            "Temporada no ano civil (ex.: 2026, em vez de 2026/27)",
            bool(cfg.get("ano_civil")), key=f"{prefixo}_civil")

        c3, c4, c5 = st.columns([1, 1, 1])
        idioma = c3.selectbox(
            "Idioma dos dias e meses", idiomas,
            index=idiomas.index(cfg.get("idioma", "pt"))
            if cfg.get("idioma", "pt") in idiomas else 0,
            format_func=lambda k: cr.IDIOMAS[k]["nome"],
            key=f"{prefixo}_idioma")
        rotulo = c4.text_input(
            "Nome da rodada", cfg.get("rotulo_rodada", ""),
            placeholder="vazio = padrão do idioma", key=f"{prefixo}_rot")
        formato = c5.text_input(
            "Formato no título", cfg.get("formato_rodada", ""),
            placeholder="{n}° {rotulo}", key=f"{prefixo}_fmt",
            help="Use {n} para o número e {rotulo} para o nome da rodada.")
        total = st.number_input("Número de rodadas (liga/fase de liga)", 1, 999,
                                min(int(cfg.get("total_rodadas") or 38), 999), 1,
                                key=f"{prefixo}_total")
        mata_mata = st.checkbox(
            "Tem fase de mata-mata (oitavas, quartas, final...)",
            bool(cfg.get("mata_mata")), key=f"{prefixo}_mm",
            help="Nas fases eliminatórias, a imagem de classificação vira o "
                 "chaveamento do mata-mata.")

        st.markdown("**Cores da faixa no topo das imagens**")
        cores = list(cfg.get("cores") or [])
        padrao_cores = ["#2470E8", "#F0F0F0", "#DE343E"]
        k1, k2, k3, k4 = st.columns([1, 1, 1, 2])
        cor1 = k1.color_picker("Cor 1", _hex(cores[0] if len(cores) > 0 else "",
                                             padrao_cores[0]),
                               key=f"{prefixo}_c1")
        cor2 = k2.color_picker("Cor 2", _hex(cores[1] if len(cores) > 1 else "",
                                             padrao_cores[1]),
                               key=f"{prefixo}_c2")
        cor3 = k3.color_picker("Cor 3", _hex(cores[2] if len(cores) > 2 else "",
                                             padrao_cores[2]),
                               key=f"{prefixo}_c3")
        tres = k4.checkbox("Usar as 3 cores", len(cores) >= 3,
                           key=f"{prefixo}_tres")


        st.markdown("**Cor do fundo das imagens**")
        atual_fundo = str(cfg.get("fundo") or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", atual_fundo):
            modo_idx, cor_fundo_ini = 2, atual_fundo
        elif atual_fundo.lower() in ("azul", "padrao", "padrão"):
            modo_idx, cor_fundo_ini = 1, cores[0] if cores else "#2470E8"
        else:
            modo_idx, cor_fundo_ini = 0, cores[0] if cores else "#2470E8"
        opcoes_fundo = ["Automático (pela cor da competição)",
                        "Azul-marinho clássico", "Escolher cor"]
        f1, f2 = st.columns([2, 1])
        modo_fundo = f1.radio(
            "Fundo", opcoes_fundo, index=modo_idx, key=f"{prefixo}_fundo_modo",
            label_visibility="collapsed",
            help="Automático usa a primeira cor com tom de verdade (ignora "
                 "branco e cinza) e gera o fundo nessa matiz (claro ou escuro, conforme o tema), com "
                 "linhas, cartões e textos no mesmo tom.")
        cor_fundo = f2.color_picker(
            "Cor do fundo (vale só em \"Escolher cor\")",
            _hex(cor_fundo_ini, "#2470E8"), key=f"{prefixo}_fundo_cor")

        st.markdown("**Fundo das imagens: tema e desenho**")
        temas = {"medio": "Meio-termo (padrão)", "claro": "Claro",
                 "escuro": "Escuro"}
        estilos = cr.ESTILOS_FUNDO
        coresl = {"mono": "Uma cor, minimalista", "original": "Cores originais"}
        g1, g2 = st.columns(2)
        tema_atual = cfg.get("tema") if cfg.get("tema") in temas else "medio"
        tema = g1.radio(
            "Tema", list(temas), horizontal=True,
            index=list(temas).index(tema_atual),
            format_func=lambda k: temas[k], key=f"{prefixo}_tema",
            help="Meio-termo: fundo na cor principal da competição, nem claro "
                 "nem escuro. A matiz vem de \"Cor do fundo\" (acima).")
        estilo_atual = cfg.get("estilo_fundo")
        if estilo_atual not in estilos:       # cadastros antigos
            estilo_atual = {"nenhuma": "nenhum", "marca": "logo"}.get(
                cfg.get("textura"), "auto")
        estilo = g2.selectbox(
            "Desenho de fundo", list(estilos),
            index=list(estilos).index(estilo_atual),
            format_func=lambda k: estilos[k], key=f"{prefixo}_estilo",
            help="Formas geométricas no tom da competição (triângulos, "
                 "zigue-zague, listras, anéis, quadriculado, estrelas, "
                 "losangos, favo de mel, bolinhas, ondas e os temáticos de "
                 "Espanha, Alemanha, França e Brasil), a sua própria "
                 "imagem (envie no quadro \"Imagem de fundo própria\" acima "
                 "do formulário) ou o logo dela, bem suave. Automático "
                 "escolhe um desenho para cada competição.")
        g3, g4 = st.columns(2)
        opac = g3.slider(
            "Intensidade do desenho (%)", 1, 25,
            max(1, min(25, int(cfg.get("textura_opacidade") or 2))),
            key=f"{prefixo}_opac")
        cor_logo = g4.radio(
            "Cor do logo (quando ele aparece)", list(coresl), horizontal=True,
            index=1 if cfg.get("textura_cor") == "original" else 0,
            format_func=lambda k: coresl[k], key=f"{prefixo}_corlogo")
        imgint = st.slider(
            "Intensidade da imagem de fundo própria (%)", 5, 70,
            max(5, min(70, int(cfg.get("fundo_imagem_intensidade") or 28))),
            key=f"{prefixo}_imgint",
            help="Vale só quando o desenho é \"Minha própria imagem\". "
                 "Quanto menor, mais discreta fica a imagem.")
        logo_sobre = st.checkbox(
            "Colocar também o logo grande, bem suave, por cima do desenho",
            bool(cfg.get("logo_sobre_padrao")), key=f"{prefixo}_logosobre")
        logo_vazio = st.checkbox(
            "Quando a agenda for dividida em duas imagens, deixar todas do "
            "mesmo tamanho e preencher o espaço que sobra com o logo da "
            "competição", bool(cfg.get("logo_no_vazio", True)),
            key=f"{prefixo}_logovazio")

        st.markdown("**Logo da competição no cabeçalho das imagens**")
        st.caption(
            "Ligue o logo só nas imagens em que quiser. Cada tipo de imagem "
            "tem o seu tamanho e a sua cor. \"Branco\" mantém os detalhes do "
            "logo (partes internas ficam translúcidas, sem virar uma mancha); "
            "\"Automático\" usa as cores originais e troca para o branco se "
            "o logo quase sumir no fundo.")
        logo_cab = {}
        for col, (tipo, rotulo_img) in zip(st.columns(3),
                                           cr.LOGO_CAB_IMAGENS.items()):
            with col:
                tams, cors = cr.LOGO_CAB_TAMANHOS, cr.LOGO_CAB_CORES
                pad = cr.PADROES_COMPETICAO     # padrões das competições novas
                tam_at = cfg.get(f"logo_cab_{tipo}_tam",
                                 pad[f"logo_cab_{tipo}_tam"])
                cor_at = cfg.get(f"logo_cab_{tipo}_cor",
                                 pad[f"logo_cab_{tipo}_cor"])
                logo_cab[f"logo_cab_{tipo}"] = st.checkbox(
                    rotulo_img,
                    bool(cfg.get(f"logo_cab_{tipo}", pad[f"logo_cab_{tipo}"])),
                    key=f"{prefixo}_lc_{tipo}")
                logo_cab[f"logo_cab_{tipo}_tam"] = st.selectbox(
                    "Tamanho", list(tams),
                    index=list(tams).index(tam_at) if tam_at in tams else 0,
                    format_func=lambda k: tams[k], key=f"{prefixo}_lct_{tipo}")
                logo_cab[f"logo_cab_{tipo}_cor"] = st.selectbox(
                    "Cor", list(cors),
                    index=list(cors).index(cor_at) if cor_at in cors else 0,
                    format_func=lambda k: cors[k], key=f"{prefixo}_lcc_{tipo}")

        destaque_logo = st.checkbox(
            "Logo da competição no fundo da imagem do jogo da rodada",
            bool(cfg.get("destaque_logo_fundo", True)),
            key=f"{prefixo}_destlogo",
            help="A imagem do jogo da rodada é gerada para os jogos marcados "
                 "com ⭐ Destaque na tabela da agenda: escudos centralizados "
                 "sobre o fundo nas cores de cada clube. Aqui você escolhe se "
                 "o logo da competição aparece grande e bem suave no fundo.")

        st.markdown("**Transmissão**")
        t1, t2 = st.columns(2)
        tv = t1.text_input("Transmissão padrão", cfg.get("tv_padrao", ""),
                           key=f"{prefixo}_tv",
                           help="Usada quando não se encontra a do jogo.")
        tv_logos = t1.checkbox(
            "Mostrar logos das emissoras na imagem da agenda (em vez do nome)",
            bool(cfg.get("tv_logos", True)), key=f"{prefixo}_logos",
            help="A coluna de transmissão fica bem mais estreita. Para usar o "
                 "logo oficial de um canal, salve um PNG na pasta 'logos'.")
        futnatv = t2.text_input(
            "Nome do campeonato no futnatv (vazio = detectar sozinho)",
            cfg.get("futnatv", ""), key=f"{prefixo}_futnatv",
            help="Deixe vazio: na primeira geração (rodada a até 7 dias) o "
                 "programa descobre sozinho como o futnatv chama o campeonato. "
                 "Se preencher, use exatamente o nome que aparece no site.")
        if cfg.get("futnatv_auto"):
            t2.caption(f"Detectado automaticamente: {cfg['futnatv_auto']}")

        st.markdown("**Faixas da classificação** (usadas quando o Sofascore não "
                    "informa; deixe 0 para não usar)")
        atuais = {z["chave"]: z for z in cfg.get("zonas", [])}
        zonas = []
        for chave, padrao in ZONAS_FORM:
            z = atuais.get(chave, {})
            za, zb, zc = st.columns([3, 1, 1])
            rot = za.text_input(f"Nome da faixa ({padrao})", z.get("rotulo", ""),
                                placeholder=padrao, key=f"{prefixo}_zr_{chave}")
            ini = zb.number_input("De", 0, 60, int(z.get("ini") or 0), 1,
                                  key=f"{prefixo}_zi_{chave}")
            fim = zc.number_input("Até", 0, 60, int(z.get("fim") or 0), 1,
                                  key=f"{prefixo}_zf_{chave}")
            zonas.append({"chave": chave, "rotulo": rot.strip(),
                          "ini": int(ini), "fim": int(fim or ini)})

        faixas_txt = st.text_area(
            "Nomes das faixas na legenda (opcional; um por linha: texto do "
            "Sofascore = nome na legenda)",
            _pares_para_texto(cfg.get("rotulos_faixas")), height=80,
            key=f"{prefixo}_faixas",
            help="O texto do Sofascore aparece no log ('faixa do Sofascore: "
                 "...') ao gerar a classificação.")

        st.markdown("**Ajuste de nomes** — edite a coluna da direita para "
                    "mudar como o nome aparece nas imagens e na agenda. "
                    "**Vale para todas as competições**, atuais e futuras.")
        glob = cr.carregar_nomes_globais()
        col_t, col_e = st.columns(2)
        with col_t:
            alt_times, rev_times = _tabela_nomes(
                "Times", cfg.get("times_sofascore"),
                {**(cfg.get("nomes_times") or {}), **glob["times"]},
                f"{prefixo}_nt")
        with col_e:
            alt_est, rev_est = _tabela_nomes(
                "Estádios", cfg.get("estadios_sofascore"),
                {**(cfg.get("nomes_estadios") or {}), **glob["estadios"]},
                f"{prefixo}_ne")
        with st.expander("Adicionar outros ajustes à mão (opcional)"):
            e1, e2 = st.columns(2)
            extra_t = e1.text_area(
                "Times (um por linha: nome no Sofascore = nome que você usa)",
                "", height=90, key=f"{prefixo}_xt")
            extra_e = e2.text_area(
                "Estádios (um por linha: nome no Sofascore = nome que você usa)",
                "", height=90, key=f"{prefixo}_xe")

        enviado = st.form_submit_button(texto_botao, type="primary")

    if not enviado:
        return None
    if not nome.strip() or int(tid) <= 0:
        st.error("Preencha o nome e o ID da competição.")
        return None
    if estilo == "imagem" and not cr.caminho_fundo_personalizado(int(tid)):
        st.error("Para usar \"Minha própria imagem\", envie a imagem primeiro "
                 "no quadro \"Imagem de fundo própria\" (acima do formulário).")
        return None
    # nomes de times/estádios: vão para o arquivo global (todas as competições)
    cr.atualizar_nomes_globais(
        times={**alt_times, **_texto_para_pares(extra_t)},
        estadios={**alt_est, **_texto_para_pares(extra_e)},
        remover_times=rev_times, remover_estadios=rev_est)
    novo = dict(cfg)
    novo.update({
        "nome": nome.strip(), "nome_curto": nome_curto.strip() or nome.strip(),
        "tournament_id": int(tid), "season_id": int(sid),
        "season_auto": bool(auto), "ano_civil": bool(civil),
        "idioma": idioma, "rotulo_rodada": rotulo.strip(),
        "formato_rodada": formato.strip(), "total_rodadas": int(total),
        "mata_mata": bool(mata_mata),
        "rotulos_faixas": _texto_para_pares(faixas_txt),
        "cores": [cor1, cor2, cor3] if tres else [cor1, cor2],
        "fundo": ("azul" if modo_fundo == opcoes_fundo[1]
                  else cor_fundo.lower() if modo_fundo == opcoes_fundo[2]
                  else ""),
        "tema": tema, "estilo_fundo": estilo, "textura_opacidade": int(opac),
        "fundo_imagem_intensidade": int(imgint),
        "logo_sobre_padrao": bool(logo_sobre),
        "textura_cor": cor_logo, "logo_no_vazio": bool(logo_vazio),
        **logo_cab, "destaque_logo_fundo": bool(destaque_logo),
        "tv_padrao": tv.strip(), "tv_logos": bool(tv_logos),
        "futnatv": futnatv.strip(),
        "zonas": zonas,
        "nomes_times": {}, "nomes_estadios": {},     # ficam no arquivo global
    })
    return novo


def _logo_atual(tid):
    for nome in (f"custom_{tid}.png", f"{tid}.png"):
        arq = cr.PASTA_LOGOS_COMP / nome
        if arq.exists():
            return arq
    return None


def bloco_logo(cfg, slug):
    """Logo da competição usado na textura e no espaço vazio da agenda."""
    tid = int(cfg.get("tournament_id") or 0)
    with st.expander("🖼️ Logo da competição (fundo e espaço vazio das imagens)"):
        atual = _logo_atual(tid)
        c1, c2 = st.columns([1, 4])
        if atual:
            c1.image(str(atual), width=110)
            c2.caption("Logo enviado por você." if atual.name.startswith("custom_")
                       else "Logo baixado do Sofascore.")
        else:
            c2.caption("Ainda não há logo. Ele é baixado do Sofascore na próxima "
                       "vez que você clicar em Gerar tópico, ou envie o seu "
                       "abaixo.")
        up = st.file_uploader(
            "Enviar um logo próprio (PNG com fundo transparente funciona melhor)",
            type=["png", "jpg", "jpeg", "webp"], key=f"logo_up_{slug}")
        if up is not None and st.button("Usar este logo", key=f"logo_usar_{slug}"):
            from PIL import Image
            cr.PASTA_LOGOS_COMP.mkdir(parents=True, exist_ok=True)
            Image.open(up).convert("RGBA").save(
                cr.PASTA_LOGOS_COMP / f"custom_{tid}.png")
            st.rerun()
        if atual and atual.name.startswith("custom_") and st.button(
                "Voltar ao logo do Sofascore", key=f"logo_volta_{slug}"):
            atual.unlink()
            st.rerun()


def bloco_fundo(cfg, slug):
    """Envio da imagem de fundo própria. O programa ajusta sozinho: recorta
    para caber, tira as cores, suaviza os detalhes e usa o tom da competição."""
    tid = int(cfg.get("tournament_id") or 0)
    chave_estilo = f"edit_{slug}_estilo"
    with st.expander("🎨 Imagem de fundo própria (ajustada automaticamente)"):
        st.caption("Envie qualquer foto ou arte. O programa recorta para o "
                   "formato das imagens, deixa em tons de uma cor só (a da "
                   "competição), suaviza os detalhes e reduz o contraste: "
                   "sobra um fundo minimalista que não atrapalha a leitura. "
                   "A força do efeito se ajusta em \"Intensidade da imagem de "
                   "fundo própria\", no formulário abaixo.")
        atual = cr.caminho_fundo_personalizado(tid)
        if atual:
            previa = cr.previa_fundo_personalizado()
            if previa is not None:
                st.image(previa, caption="Prévia com o tema e as cores salvos "
                                         "desta competição",
                         use_container_width=True)
            if cfg.get("estilo_fundo") != "imagem":
                st.info("Há uma imagem enviada, mas o desenho de fundo "
                        "escolhido não é \"Minha própria imagem\". Selecione "
                        "essa opção no formulário abaixo para usá-la.")
        up = st.file_uploader(
            "Enviar uma imagem de fundo (JPG, PNG ou WEBP)",
            type=["png", "jpg", "jpeg", "webp"], key=f"fundo_up_{slug}")
        if up is not None and st.button("Usar esta imagem de fundo",
                                        key=f"fundo_usar_{slug}"):
            try:
                cr.salvar_fundo_personalizado(tid, up.getvalue())
            except Exception as exc:  # noqa
                st.error(f"Não consegui abrir essa imagem: {exc}")
            else:
                novo = dict(cfg)
                novo["estilo_fundo"] = "imagem"
                cr.salvar_competicao(slug, novo)
                st.session_state[chave_estilo] = "imagem"
                st.rerun()
        if atual and st.button("Remover a imagem de fundo",
                               key=f"fundo_rem_{slug}"):
            cr.remover_fundo_personalizado(tid)
            if cfg.get("estilo_fundo") == "imagem":
                novo = dict(cfg)
                novo["estilo_fundo"] = "auto"
                cr.salvar_competicao(slug, novo)
                st.session_state[chave_estilo] = "auto"
            st.rerun()


def aba_competicoes(competicoes, slug):
    st.subheader(f"Editar: {competicoes[slug]['nome']}")
    if st.button("🔄 Buscar times e estádios no Sofascore",
                 key=f"buscar_nomes_{slug}",
                 help="Lê os times, os estádios e as rodadas/fases da temporada "
                      "atual. Leva cerca de 20 segundos."):
        with st.spinner("Consultando o Sofascore..."):
            dados, log = buscar_nomes(slug)
        if dados:
            atual = dict(competicoes[slug])
            atual["times_sofascore"] = dados["times"]
            atual["estadios_sofascore"] = dados["estadios"]
            if dados.get("rodadas"):
                atual["rodadas"] = dados["rodadas"]
                atual["mata_mata"] = bool(dados.get("mata_mata"))
            cr.salvar_competicao(slug, atual)
            st.rerun()
        else:
            ult = [l for l in log.splitlines() if l.strip()]
            st.error("Não consegui ler os nomes agora.")
            st.code("\n".join(ult[-5:]), language=None)
    if st.button("✂️ Encurtar nomes de times e estádios (todas as competições)",
                 key=f"encurtar_{slug}",
                 help="Cria nomes mais coloquiais (sem FC, SC, Stadio, Estadio "
                      "etc.) para tudo que ainda não tem ajuste. Não mexe no "
                      "que você já ajustou. Vale para todas as competições."):
        novos_t, novos_e = cr.encurtar_todos_os_nomes()
        st.session_state["_msg_encurtar"] = (
            f"{len(novos_t)} times e {len(novos_e)} estádios encurtados. "
            f"Confira e ajuste nas tabelas abaixo.")
        st.rerun()
    if "_msg_encurtar" in st.session_state:
        st.success(st.session_state.pop("_msg_encurtar"))
    bloco_logo(competicoes[slug], slug)
    bloco_fundo(competicoes[slug], slug)
    novo = formulario_competicao(f"edit_{slug}", competicoes[slug],
                                 "Salvar alterações")
    if novo:
        cr.salvar_competicao(slug, novo)
        st.success("Alterações salvas.")
        st.rerun()
    if len(competicoes) > 1:
        with st.expander("Remover esta competição"):
            if st.checkbox("Confirmo que quero remover", key=f"conf_{slug}") \
                    and st.button("🗑️ Remover", key=f"rem_{slug}"):
                cr.remover_competicao(slug)
                st.rerun()

    st.divider()
    st.subheader("Cadastrar nova competição")
    st.caption("Abra a página do campeonato no Sofascore e cole o link aqui "
               "(ele termina com um número). Se o link tiver `#id:` no fim, "
               "essa temporada é a escolhida; senão, a mais recente.")
    link = st.text_input("Link da competição no Sofascore", key="link_novo",
                         placeholder="https://www.sofascore.com/pt/futebol/"
                                     "torneio/brazil/brasileirao-serie-a/325")
    if st.button("🔍 Buscar dados no Sofascore"):
        with st.spinner("Consultando o Sofascore..."):
            dados, log = buscar_link(link)
        if dados:
            st.session_state["novo"] = cr.cfg_inicial_do_link(dados)
            st.session_state["novo_info"] = dados
        else:
            st.session_state.pop("novo", None)
            ult = [l for l in log.splitlines() if l.strip()]
            st.error("Não consegui ler esse link.")
            st.code("\n".join(ult[-5:]), language=None)

    novo_cfg = st.session_state.get("novo")
    if novo_cfg:
        info = st.session_state.get("novo_info", {})
        st.success(f"Encontrei: **{novo_cfg['nome']}** ({info.get('pais', '')}), "
                   f"temporada {info.get('temporada', '?')}. Confira os campos "
                   f"abaixo e salve.")
        criado = formulario_competicao(f"novo_{novo_cfg['tournament_id']}",
                                       novo_cfg, "Salvar nova competição")
        if criado:
            nova_chave = cr.salvar_competicao(None, criado)
            st.session_state.pop("novo", None)
            st.session_state["_comp_nova"] = nova_chave
            st.rerun()


# ------------------------------------------------------------------ barra lateral
competicoes = cr.carregar_competicoes()
chaves = list(competicoes)
if "_comp_nova" in st.session_state:       # recém-cadastrada: já seleciona
    st.session_state["comp"] = st.session_state.pop("_comp_nova")
if st.session_state.get("comp") not in chaves:
    st.session_state["comp"] = chaves[0]

with st.sidebar:
    st.header("⚽ Rodada Pronta")
    slug = st.selectbox("Competição", chaves, key="comp",
                        format_func=lambda k: competicoes[k]["nome"])
    cfg = competicoes[slug]
    cr.aplicar_competicao(cfg)             # dias/meses/cores da competição

    modo = st.radio("Qual rodada?", ["Próxima (automático)", "Escolher"],
                    key=f"modo_{slug}")
    numero, chave = None, None
    if modo.startswith("Escolher"):
        rodadas = cfg.get("rodadas") or []
        if rodadas:
            rotulos = {cr.chave_rodada(r): cr.rotulo_rodada(r) for r in rodadas}
            salva = (ultima_rodada(slug) or {}).get("chave")
            opcoes = list(rotulos)
            chave = st.selectbox(
                "Rodada / fase", opcoes, key=f"rod_{slug}",
                index=opcoes.index(salva) if salva in opcoes else 0,
                format_func=lambda k: rotulos[k])
        else:
            maximo = min(int(cfg.get("total_rodadas") or 60), 999)
            salva = (ultima_rodada(slug) or {}).get("rodada") or 1
            numero = int(st.number_input("Número da rodada", 1, maximo,
                                         value=min(max(salva, 1), maximo),
                                         step=1, key=f"num_{slug}"))
    gerar_img = st.checkbox("Gerar imagens", value=True)
    buscar_tv = st.checkbox("Buscar transmissões no futnatv", value=True,
                            key=f"tv_{slug}")
    gerar = st.button("Gerar tópico", type="primary", use_container_width=True)
    if os.name == "nt" and st.button("📂 Abrir pasta dos arquivos",
                                      use_container_width=True):
        (SAIDA / slug).mkdir(parents=True, exist_ok=True)
        os.startfile(SAIDA / slug)  # noqa

est = st.session_state.setdefault(
    f"est_{slug}", {"gen": 0, "log": "", "ok": None, "rodada": None})

if gerar:
    with st.spinner("Buscando dados... isso pode levar de 1 a 3 minutos. "
                    "Na primeira vez pode demorar mais."):
        codigo, log = executar(slug, numero, chave, gerar_img, buscar_tv)
    est["log"] = log
    est["ok"] = codigo == 0
    est["gen"] += 1
    if codigo == 0:
        est["rodada"] = ultima_rodada(slug)

aba_topico, aba_comp = st.tabs(["Tópico da rodada", "Competições"])

# ------------------------------------------------------------------ aba tópico
with aba_topico:
    st.title(f"Tópico da rodada — {cfg['nome']}")

    if est.get("ok") is False:
        st.error("Algo deu errado ao buscar os dados. Abra os 'Detalhes "
                 "técnicos' no fim da página e envie o texto para quem mantém "
                 "o programa.")
        ultimas = [l for l in est.get("log", "").splitlines() if l.strip()]
        st.code("\n".join(ultimas[-6:]), language=None)

    ultima = est.get("rodada") or ultima_rodada(slug)
    rodada = ultima["pasta"] if ultima else None
    pasta = SAIDA / slug / rodada if rodada else None

    if not pasta or not (pasta / "jogos.json").exists():
        st.info("Clique em **Gerar tópico** na barra lateral para começar.")
    else:
        titulo = (pasta / "titulo.txt").read_text(encoding="utf-8").strip()
        jogos = json.loads((pasta / "jogos.json").read_text(encoding="utf-8"))
        for j in jogos:
            j["inicio"] = datetime.fromisoformat(j["inicio"])
            j["tv"] = cr.limpar_transmissao(j["tv"])
        # dados "puros" (sem edições) e edições salvas da rodada: o que você
        # marca/corrige aqui fica gravado em edicoes.json e volta ao reabrir
        base = {j["confronto"]: {"estadio": j["estadio"], "tv": j["tv"]}
                for j in jogos}
        edicoes_salvas = cr.carregar_edicoes(pasta)
        jogos = cr.aplicar_edicoes(jogos, edicoes_salvas)
        ver = st.session_state.get(f"ver_{slug}_{rodada}", 0)
        pref = f"{slug}_{rodada}_{est['gen']}_{ver}"

        st.subheader("1. Título do tópico")
        st.code(titulo, language=None)

        st.subheader("2. Agenda de jogos")
        st.caption("Confira o estádio e a transmissão (dê dois cliques na "
                   "célula para corrigir). Marque **⭐ Destaque** nos jogos "
                   "que merecem destaque na agenda (clássico, jogo decisivo...); "
                   "o rótulo pode ser trocado na coluna **Rótulo**. As "
                   "plataformas pagas de streaming (Disney+, Prime Video...) só "
                   "aparecem na agenda quando são a única transmissão do jogo; "
                   "marque **💳 Streamings** para mostrá-las sempre naquele "
                   "jogo. Suas edições ficam salvas, mesmo fechando o programa.")
        rotulo_padrao = st.text_input(
            "Rótulo padrão dos jogos em destaque",
            edicoes_salvas.get("_rotulo_padrao") or cr.DESTAQUE_ROTULO_PADRAO,
            key=f"rotulo_padrao_{pref}",
            help="Usado quando a coluna Rótulo de um jogo marcado fica vazia.")
        chave_tab = f"tabela_{pref}"
        if chave_tab not in st.session_state:   # tabela estável entre cliques
            st.session_state[chave_tab] = pd.DataFrame([{
                "Dia": f"{cr.DIAS[j['inicio'].weekday()]}, {j['inicio'].day} "
                       f"{cr.MESES[j['inicio'].month]}",
                "Hora": j["hora"],
                "Jogo": j["confronto"],
                "⭐ Destaque": bool(j.get("destaque", False)),
                "Rótulo": str(j.get("rotulo") or ""),
                "Estádio": j["estadio"],
                "Transmissão": j["tv"],
                "💳 Streamings": bool(j.get("tv_streamings", False)),
            } for j in jogos])
        editado = st.data_editor(
            st.session_state[chave_tab], hide_index=True,
            use_container_width=True,
            disabled=["Dia", "Hora", "Jogo"],
            column_config={
                "⭐ Destaque": st.column_config.CheckboxColumn(
                    "⭐ Destaque", default=False,
                    help="Destaca o jogo na agenda e gera a imagem do jogo da rodada "
                         "(escudos com as cores dos clubes)."),
                "Rótulo": st.column_config.TextColumn(
                    "Rótulo",
                    help="Texto do selo do jogo em destaque (ex.: Clássico, "
                         "Decisão). Vazio = rótulo padrão."),
                "Transmissão": st.column_config.TextColumn(
                    "Transmissão",
                    help="Lista completa de canais. Streamings pagos só "
                         "aparecem na agenda se forem a única opção (ou se "
                         "💳 Streamings estiver marcado). Premiere sempre "
                         "aparece, no fim da lista."),
                "💳 Streamings": st.column_config.CheckboxColumn(
                    "💳 Streamings", default=False,
                    help="Mostrar também as plataformas pagas (Disney+, "
                         "Prime Video, HBO Max...) neste jogo."),
            },
            key=f"editor_{pref}")
        for i, linha in enumerate(editado.to_dict("records")):
            jogos[i]["estadio"] = str(linha["Estádio"]).strip()
            jogos[i]["tv"] = str(linha["Transmissão"]).strip()
            jogos[i]["destaque"] = bool(linha.get("⭐ Destaque"))
            jogos[i]["tv_streamings"] = bool(linha.get("💳 Streamings"))
            rot = linha.get("Rótulo")
            rot = "" if rot is None or pd.isna(rot) else str(rot).strip()
            jogos[i]["rotulo"] = rot
            jogos[i]["destaque_rotulo"] = rot or rotulo_padrao.strip() \
                or cr.DESTAQUE_ROTULO_PADRAO

        # cores de fundo da imagem do jogo da rodada (por clube)
        destacados = [i for i, j in enumerate(jogos) if j["destaque"]]
        if destacados:
            with st.expander("🎨 Cores do fundo da imagem do jogo da rodada"):
                st.caption("Por padrão a cor de cada lado vem do escudo do "
                           "clube. Marque **Escolher cor** para definir o "
                           "tom do fundo à mão (o campo mostra a cor "
                           "automática de partida).")
                for i in destacados:
                    j = jogos[i]
                    st.markdown(f"**{j['confronto']}**")
                    auto = cr.tons_automaticos(j)
                    for col, lado, nome, a in zip(
                            st.columns(2), ("cor_mandante", "cor_visitante"),
                            (j["mandante"], j["visitante"]), auto):
                        with col:
                            pers = st.checkbox(
                                f"Escolher cor — {nome}", bool(j.get(lado)),
                                key=f"cor_p_{pref}_{i}_{lado}")
                            cor = st.color_picker(
                                f"Cor do fundo — {nome}", j.get(lado) or a,
                                key=f"cor_c_{pref}_{i}_{lado}",
                                disabled=not pers,
                                label_visibility="collapsed")
                            j[lado] = cor if pers else ""

        # grava as edições (só o que mudou) para não se perderem
        cr.salvar_edicoes(pasta, cr.montar_edicoes(
            jogos, base, rotulo_padrao))
        if edicoes_salvas and st.button(
                "↩️ Desfazer minhas edições desta rodada",
                key=f"desfazer_{pref}",
                help="Volta ao que veio do Sofascore: sem destaques, "
                     "transmissões originais e cores automáticas."):
            cr.salvar_edicoes(pasta, {})
            st.session_state[f"ver_{slug}_{rodada}"] = ver + 1
            st.rerun()

        texto = cr.formatar_agenda(jogos)
        (pasta / "agenda.txt").write_text(texto, encoding="utf-8")
        try:  # as imagens da agenda acompanham as correções feitas na tabela
            cr.gerar_agendas(jogos, titulo, pasta)
        except Exception:  # noqa
            pass
        try:  # uma imagem (sem texto) para cada jogo marcado como destaque
            cr.gerar_imagens_destaque(jogos, pasta)
        except Exception:  # noqa
            pass
        st.markdown("**Texto pronto para colar no fórum** "
                    "(use o ícone de copiar no canto direito da caixa):")
        st.code(texto, language=None)

        st.subheader("3. Imagens")
        existentes = listar_imagens(pasta)
        if "AVISO_IMAGENS" in est.get("log", ""):
            st.warning("As imagens não puderam ser geradas desta vez. A agenda "
                       "está pronta; tente gerar de novo mais tarde.")
        if existentes:
            entradas = list(existentes)
            if not any(a_.startswith("resultados") for a_, _ in entradas):
                # rodada gerada antes dos resultados existirem: aba só com o botão
                pos = next((k for k, (a_, _) in enumerate(entradas)
                            if not a_.startswith(("agenda", "destaque"))),
                           len(entradas))
                entradas.insert(pos, (None, "Resultados"))
            abas = st.tabs([n for _, n in entradas])
            for aba, (arq, nome) in zip(abas, entradas):
                with aba:
                    if arq is None or arq.startswith("resultados"):
                        bloco_resultados(slug, ultima, pasta, arq or "novo",
                                         rodada)
                    if arq is None:
                        st.caption("Ainda não há imagem de resultados desta "
                                   "rodada. Clique em Atualizar Resultados.")
                        continue
                    b64 = base64.b64encode((pasta / arq).read_bytes()).decode()
                    st.markdown(
                        f'<img src="data:image/png;base64,{b64}" '
                        f'style="width:{960 if arq.startswith(("agenda", "chave", "destaque", "f2_")) else 540}px;'
                        f'max-width:100%">',
                        unsafe_allow_html=True)
                    st.download_button(f"⬇️ Baixar {nome}",
                                       data=(pasta / arq).read_bytes(),
                                       file_name=f"{slug}_{rodada}_{arq}",
                                       mime="image/png",
                                       key=f"dl_{slug}_{arq}_{rodada}")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for arq, _ in existentes:
                    z.write(pasta / arq, arcname=f"{rodada}_{arq}")
            st.download_button("⬇️ Baixar todas as imagens (.zip)",
                               data=buf.getvalue(),
                               file_name=f"{slug}_{rodada}_imagens.zip",
                               mime="application/zip",
                               key=f"zip_{slug}_{rodada}")
        else:
            st.caption("Nenhuma imagem gerada para esta rodada.")

    if est.get("log"):
        with st.expander("Detalhes técnicos"):
            st.code(est["log"], language=None)

# ------------------------------------------------------------------ aba competições
with aba_comp:
    aba_competicoes(competicoes, slug)
