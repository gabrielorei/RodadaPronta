#!/usr/bin/env python3
"""
Gerador de tópico da rodada do Calcio (Serie A) a partir do Sofascore.

Uso:
    python rodada_pronta.py          (sem número: descobre a próxima rodada)
    python rodada_pronta.py --10     (rodada específica)
    python rodada_pronta.py --10 --sem-imagens
    python rodada_pronta.py --10 --debug      (salva os JSONs brutos p/ conferência)
    python rodada_pronta.py --competicao brasileirao --10   (outra competição
                                                     cadastrada no painel)

Instalação:
    pip install curl_cffi pillow tzdata
    (plano B, se o Sofascore devolver 403:)
    pip install playwright && playwright install chromium

Saída (pasta saida/<competição>/rodada_N/):
    titulo.txt, agenda.txt, agenda.png, classificacao.png, gols.png, assistencias.png,
    defesas.png, notas.png
    (e, pelo painel, resultados.png: placares da rodada)
"""

import argparse
import copy
import difflib
import io
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# CONFIGURAÇÃO  (ajuste aqui)
# --------------------------------------------------------------------------
TOURNAMENT_ID = 23          # Serie A
SEASON_ID = 95836           # ID da temporada (o número depois de #id: na URL)
FUSO = ZoneInfo("America/Sao_Paulo")   # horário de Brasília
TV_PADRAO = "Disney+"       # usado quando o jogo não está em transmissoes.json
TOP_N = 10                  # quantos aparecem em cada imagem
PASTA_BASE = Path(__file__).resolve().parent
ARQ_TRANSMISSOES = PASTA_BASE / "transmissoes.json"
TITULO_COMPETICAO = "Série A Enilive"   # nome usado no título do tópico

BASE = "https://api.sofascore.com/api/v1"

DIAS = {0: "Lunedi", 1: "Martedì", 2: "Mercoledì", 3: "Giovedì",
        4: "Venerdì", 5: "Sabato", 6: "Domenica"}
MESES = {1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile", 5: "Maggio",
         6: "Giugno", 7: "Luglio", 8: "Agosto", 9: "Settembre",
         10: "Ottobre", 11: "Novembre", 12: "Dicembre"}

# Nome do Sofascore -> nome que você usa no fórum (complete conforme precisar)
NOMES_TIMES = {
    "AC Milan": "Milan",
    "Inter": "Internazionale",
    "AS Roma": "Roma",
    "Hellas Verona": "Verona",
    "SSC Napoli": "Napoli",
    "ACF Fiorentina": "Fiorentina",
}

# Nome do estádio no Sofascore -> nome que você usa (complete conforme precisar)
NOMES_ESTADIOS = {
    "Stadio Giuseppe Meazza": "San Siro",
    "San Siro/Giuseppe Meazza": "San Siro",
    "Mapei Stadium": "MAPEI Stadium",
    "San Siro": "San Siro",
    "Stadio Olimpico": "Olimpico",
    "Stadio Artemio Franchi": "Artêmio Franchi",
    "Stadio Diego Armando Maradona": "Diego Armando Maradona",
    "Stadio Ennio Tardini": "Ennio Tardini",
    "Allianz Stadium": "Allianz Stadium",
    "Gewiss Stadium": "New Balance Arena",
    "Stadio Via del Mare": "Via del Mare",
    "Unipol Domus": "Unipol Domus",
}

# --------------------------------------------------------------------------
# COMPETIÇÕES  (ficam em competicoes.json; o painel edita esse arquivo)
# --------------------------------------------------------------------------
IDIOMAS = {
    "pt": {"nome": "Português", "rotulo": "Rodada", "formato": "{n}ª {rotulo}",
           "dias": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado",
                    "Domingo"],
           "meses": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                     "Julho", "Agosto", "Setembro", "Outubro", "Novembro",
                     "Dezembro"]},
    "it": {"nome": "Italiano", "rotulo": "Giornata", "formato": "{n}° {rotulo}",
           "dias": ["Lunedi", "Martedì", "Mercoledì", "Giovedì", "Venerdì",
                    "Sabato", "Domenica"],
           "meses": ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio",
                     "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre",
                     "Novembre", "Dicembre"]},
    "es": {"nome": "Espanhol", "rotulo": "Jornada", "formato": "{rotulo} {n}",
           "dias": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes",
                    "Sábado", "Domingo"],
           "meses": ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                     "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                     "Diciembre"]},
    "en": {"nome": "Inglês", "rotulo": "Matchday", "formato": "{rotulo} {n}",
           "dias": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                    "Saturday", "Sunday"],
           "meses": ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December"]},
    "fr": {"nome": "Francês", "rotulo": "Journée", "formato": "{rotulo} {n}",
           "dias": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi",
                    "Samedi", "Dimanche"],
           "meses": ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
                     "Juillet", "Août", "Septembre", "Octobre", "Novembre",
                     "Décembre"]},
    "de": {"nome": "Alemão", "rotulo": "Spieltag", "formato": "{n}. {rotulo}",
           "dias": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                    "Samstag", "Sonntag"],
           "meses": ["Januar", "Februar", "März", "April", "Mai", "Juni",
                     "Juli", "August", "September", "Oktober", "November",
                     "Dezember"]},
}

ARQ_COMPETICOES = PASTA_BASE / "competicoes.json"
ARQ_NOMES = PASTA_BASE / "nomes_globais.json"

# --------------------------------------------------------------------------
# NOMES GLOBAIS (valem para TODAS as competições, atuais e futuras)
# Ficam em nomes_globais.json: {"times": {...}, "estadios": {...}}
# --------------------------------------------------------------------------
def carregar_nomes_globais():
    dados = {}
    if ARQ_NOMES.exists():
        try:
            dados = json.loads(ARQ_NOMES.read_text(encoding="utf-8"))
        except Exception:  # noqa
            dados = {}
    return {"times": dict(dados.get("times") or {}),
            "estadios": dict(dados.get("estadios") or {})}


def _gravar_nomes_globais(g):
    ARQ_NOMES.write_text(json.dumps(g, ensure_ascii=False, indent=2,
                                    sort_keys=True), encoding="utf-8")


def atualizar_nomes_globais(times=None, estadios=None, remover_times=(),
                            remover_estadios=(), sobrescrever=True):
    """Grava nomes no arquivo global. sobrescrever=False só acrescenta o que
    ainda não existe (usado ao importar nomes antigos de uma competição)."""
    g = carregar_nomes_globais()
    for chave, novos, remover in (("times", times, remover_times),
                                  ("estadios", estadios, remover_estadios)):
        for k in remover or ():
            g[chave].pop(k, None)
        for k, v in (novos or {}).items():
            if v and (sobrescrever or k not in g[chave]):
                g[chave][k] = v
    _gravar_nomes_globais(g)
    return g


def _migrar_nomes_locais(dados):
    """Move os nomes que estavam dentro de cada competição para o arquivo
    global (sem sobrescrever o que já existe lá). Retorna True se mudou algo."""
    mudou = False
    for cfg in dados.values():
        t, e = cfg.get("nomes_times"), cfg.get("nomes_estadios")
        if t or e:
            atualizar_nomes_globais(t, e, sobrescrever=False)
            cfg["nomes_times"], cfg["nomes_estadios"] = {}, {}
            mudou = True
    return mudou

# A Série A é a competição que já vem cadastrada.
COMPETICAO_SERIE_A = {
    "nome": TITULO_COMPETICAO,
    "nome_curto": "Serie A",
    "tournament_id": TOURNAMENT_ID,
    "season_id": SEASON_ID,
    "season_auto": False,
    "ano_civil": False,
    "idioma": "it",
    "rotulo_rodada": "Giornata",
    "formato_rodada": "{n}° {rotulo}",
    "cores": ["#009246", "#F0F0F0", "#CE2B37"],
    "tv_padrao": TV_PADRAO,
    "futnatv": "Campeonato Italiano",
    "total_rodadas": 38,
    "zonas": [
        {"chave": "cl", "rotulo": "Champions League", "ini": 1, "fim": 4},
        {"chave": "el", "rotulo": "Europa League", "ini": 5, "fim": 5},
        {"chave": "ecl", "rotulo": "Conference League", "ini": 6, "fim": 6},
        {"chave": "rel", "rotulo": "Rebaixamento", "ini": 18, "fim": 20},
    ],
    "nomes_times": dict(NOMES_TIMES),
    "nomes_estadios": dict(NOMES_ESTADIOS),
    "prefixo_estadio": "Stadio ",
}

PADROES_COMPETICAO = {
    "nome": "Competição", "nome_curto": "", "tournament_id": 0, "season_id": 0,
    "season_auto": True, "ano_civil": False, "idioma": "pt",
    "rotulo_rodada": "", "formato_rodada": "",
    "cores": ["#2470E8", "#F0F0F0", "#DE343E"],
    "fundo": "",   # "" = pela cor da competição | "azul" | "#RRGGBB"
    "tema": "medio",            # "medio" (padrão) | "claro" | "escuro"
    "estilo_fundo": "auto",     # ver ESTILOS_FUNDO
    "logo_sobre_padrao": False, # logo grande e suave por cima do desenho
    "textura_opacidade": 7,     # 1-25 (%): intensidade do desenho de fundo
    "textura_cor": "mono",      # "mono" (uma cor) | "original"
    "logo_no_vazio": True,      # logo no espaço vazio da agenda dividida
    # logo no cabeçalho de cada tipo de imagem (ligado/tamanho/cor):
    # padrão = pequeno e branco na agenda e na classificação; sem logo nas stats
    "logo_cab_agenda": True, "logo_cab_agenda_tam": "pequeno",
    "logo_cab_agenda_cor": "branco",
    "logo_cab_classificacao": True, "logo_cab_classificacao_tam": "pequeno",
    "logo_cab_classificacao_cor": "branco",
    "logo_cab_stats": False, "logo_cab_stats_tam": "pequeno",
    "logo_cab_stats_cor": "branco",
    "destaque_logo_fundo": True,   # logo da competição no fundo da imagem do jogo
    "tv_padrao": "", "tv_logos": True, "futnatv": "", "futnatv_auto": "",
    "rotulos_faixas": {},
    "total_rodadas": 60, "zonas": [],
    "nomes_times": {}, "nomes_estadios": {}, "prefixo_estadio": "",
}

CFG = {}   # competição em uso (preenchida por aplicar_competicao)
SLUG_ATUAL = ""


def _slug(texto):
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _gravar_competicoes(dados):
    ARQ_COMPETICOES.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_competicoes():
    dados = {}
    if ARQ_COMPETICOES.exists():
        try:
            dados = json.loads(ARQ_COMPETICOES.read_text(encoding="utf-8"))
        except Exception:  # noqa
            dados = {}
    if not dados:
        dados = {"serie-a": copy.deepcopy(COMPETICAO_SERIE_A)}
        _gravar_competicoes(dados)
    if _migrar_nomes_locais(dados):      # nomes por competição -> global
        _gravar_competicoes(dados)
    return dados


def salvar_competicao(slug, cfg):
    """Grava (ou cria, se slug for None) uma competição. Retorna a chave."""
    todas = carregar_competicoes()
    if not slug:
        base = _slug(cfg.get("nome")) or f"competicao-{cfg.get('tournament_id')}"
        slug, n = base, 2
        while slug in todas:
            slug, n = f"{base}-{n}", n + 1
    todas[slug] = cfg
    _migrar_nomes_locais(todas)          # nomes vão para o arquivo global
    _gravar_competicoes(todas)
    return slug


def remover_competicao(slug):
    todas = carregar_competicoes()
    if slug in todas and len(todas) > 1:
        del todas[slug]
        _gravar_competicoes(todas)


def completar_competicao(cfg):
    c = {**copy.deepcopy(PADROES_COMPETICAO), **cfg}
    idi = IDIOMAS.get(c["idioma"], IDIOMAS["pt"])
    c["rotulo_rodada"] = c.get("rotulo_rodada") or idi["rotulo"]
    c["formato_rodada"] = c.get("formato_rodada") or idi["formato"]
    c["nome_curto"] = c.get("nome_curto") or c["nome"]
    if not c.get("cores"):
        c["cores"] = list(PADROES_COMPETICAO["cores"])
    return c


def aplicar_competicao(sel, resolver=False):
    """Configura o módulo para a competição escolhida (chave ou dicionário).
    Com resolver=True, descobre a temporada atual no Sofascore se a
    competição estiver marcada como 'temporada automática'."""
    global CFG, TOURNAMENT_ID, SEASON_ID, TITULO_COMPETICAO, TV_PADRAO
    global DIAS, MESES, NOMES_TIMES, NOMES_ESTADIOS, CAMPEONATO_ALVO
    global PREFIXO_ESTADIO, SLUG_ATUAL
    SLUG_ATUAL = "" if isinstance(sel, dict) else sel
    if isinstance(sel, dict):
        cfg = sel
    else:
        todas = carregar_competicoes()
        if sel not in todas:
            raise RuntimeError(f"A competição '{sel}' não está cadastrada.")
        cfg = todas[sel]
    CFG = completar_competicao(cfg)
    TOURNAMENT_ID = int(CFG["tournament_id"])
    SEASON_ID = int(CFG["season_id"] or 0)
    TITULO_COMPETICAO = CFG["nome"]
    TV_PADRAO = CFG["tv_padrao"]
    CAMPEONATO_ALVO = CFG["futnatv"] or CFG.get("futnatv_auto", "")
    g = carregar_nomes_globais()         # global vale para todas as competições
    NOMES_TIMES = {**CFG["nomes_times"], **g["times"]}
    NOMES_ESTADIOS = {**CFG["nomes_estadios"], **g["estadios"]}
    PREFIXO_ESTADIO = CFG["prefixo_estadio"]
    idi = IDIOMAS.get(CFG["idioma"], IDIOMAS["pt"])
    DIAS = dict(enumerate(idi["dias"]))
    MESES = dict(enumerate(idi["meses"], start=1))
    if resolver and CFG.get("season_auto"):
        resolver_temporada()
    return CFG


def resolver_temporada():
    global SEASON_ID
    try:
        lista = get(f"/unique-tournament/{TOURNAMENT_ID}/seasons").get("seasons", [])
        if lista:
            SEASON_ID = int(lista[0]["id"])
            print(f"Temporada detectada: {lista[0].get('name') or lista[0].get('year')}"
                  f" (id {SEASON_ID})")
    except Exception as e:  # noqa
        print(f"  (não consegui detectar a temporada: {e}; usando o ID cadastrado)")


SIGLAS_CLUBE = {
    "fc", "sc", "ec", "sv", "ac", "as", "ss", "ssc", "us", "afc", "cf", "cd",
    "ud", "rc", "rcd", "sd", "sk", "fk", "bk", "if", "ik", "ifk", "ca", "kv",
    "krc", "ksc", "kaa", "fsv", "tsg", "tsv", "vfb", "vfl", "sl", "bsc", "ogc",
    "rsc", "gnk", "nk", "hnk",
}


def limpar_nome_time(nome):
    """Tira siglas de clube do começo/fim do nome: 'AC Milan' -> 'Milan',
    '1. FC Köln' -> 'Köln', 'Brighton FC' -> 'Brighton'."""
    partes = nome.split()

    def sigla(p):
        return re.sub(r"[.\-]", "", p).lower() in SIGLAS_CLUBE

    mudou = True
    while mudou and len(partes) > 1:
        mudou = False
        if sigla(partes[0]) or re.fullmatch(r"\d+\.", partes[0]):
            partes.pop(0)
            mudou = True
        elif len(partes) > 1 and sigla(partes[-1]):
            partes.pop()
            mudou = True
    limpo = " ".join(partes).strip()
    return limpo if len(limpo) >= 3 else nome


# --------------------------------------------------------------------------
# NOMES CURTOS / COLOQUIAIS (sugestão automática para times e estádios)
# --------------------------------------------------------------------------
TIMES_COLOQUIAIS = {
    "Brighton & Hove Albion": "Brighton", "Wolverhampton Wanderers": "Wolverhampton",
    "Newcastle United": "Newcastle", "West Ham United": "West Ham",
    "Leeds United": "Leeds", "Tottenham Hotspur": "Tottenham",
    "Bayer 04 Leverkusen": "Leverkusen", "Bayer Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "Gladbach", "Borussia M'gladbach": "Gladbach",
    "Borussia Dortmund": "Dortmund", "Bayern München": "Bayern",
    "FC Bayern München": "Bayern", "Eintracht Frankfurt": "Frankfurt",
    "Paris Saint-Germain": "PSG", "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille", "Olympique Marseille": "Marseille",
    "Stade Rennais": "Rennes", "LOSC Lille": "Lille", "Athletic Club": "Athletic Bilbao",
    "Atlético Madrid": "Atlético de Madrid", "Real Betis": "Betis",
    "Celta Vigo": "Celta", "Deportivo Alavés": "Alavés", "Rayo Vallecano": "Rayo Vallecano",
    "Sporting CP": "Sporting", "Sporting Lisbon": "Sporting", "SL Benfica": "Benfica",
    "FC Internazionale Milano": "Internazionale", "Inter": "Internazionale",
}

ESTADIOS_COLOQUIAIS = {
    "Coliseum Alfonso Pérez": "Coliseum", "Coliseum Alfonso Perez": "Coliseum",
    "Estadio Santiago Bernabéu": "Bernabéu", "Santiago Bernabéu": "Bernabéu",
    "Spotify Camp Nou": "Camp Nou", "Estadi Olímpic Lluís Companys": "Montjuïc",
    "Riyadh Air Metropolitano": "Metropolitano", "Estadio Metropolitano": "Metropolitano",
    "Cívitas Metropolitano": "Metropolitano",
    "Estadio Ramón Sánchez-Pizjuán": "Sánchez-Pizjuán",
    "Estadio Benito Villamarín": "Benito Villamarín",
    "Estadio de la Cerámica": "La Cerámica", "Estadio de Mestalla": "Mestalla",
    "Nuevo San Mamés": "San Mamés", "Estadio Nuevo San Mamés": "San Mamés",
    "Etihad Stadium": "Etihad", "Emirates Stadium": "Emirates",
    "Tottenham Hotspur Stadium": "Tottenham Stadium", "London Stadium": "London Stadium",
    "Stade Vélodrome": "Vélodrome", "Orange Vélodrome": "Vélodrome",
    "Estádio do Dragão": "Dragão", "Estádio da Luz": "Luz",
    "Estádio José Alvalade": "Alvalade", "Johan Cruijff ArenA": "Johan Cruijff Arena",
}

PREFIXOS_ESTADIO = ("Stadio ", "Estadio de la ", "Estadio de ", "Estadio ",
                    "Estadi ", "Stade de la ", "Stade de ", "Stade ", "Stadion ",
                    "Estádio do ", "Estádio da ", "Estádio de ", "Estádio ")

SUFIXOS_TIME = (" Club de Fútbol", " Football Club", " Futbol Club", " Calcio")


def encurtar_time(nome):
    """Sugestão de nome coloquial para um time ('Girona FC' -> 'Girona')."""
    if nome in TIMES_COLOQUIAIS:
        return TIMES_COLOQUIAIS[nome]
    n = nome
    for suf in SUFIXOS_TIME:
        if n.endswith(suf) and len(n) - len(suf) >= 3:
            n = n[: -len(suf)]
    n = re.sub(r"\s+(18|19|20)\d{2}$", "", n)      # 'Hoffenheim 1899' etc.
    return limpar_nome_time(n)


def encurtar_estadio(nome):
    """Sugestão de nome coloquial para um estádio, sem 'Stadio/Estadio/...'."""
    if nome in ESTADIOS_COLOQUIAIS:
        return ESTADIOS_COLOQUIAIS[nome]
    for pre in PREFIXOS_ESTADIO:
        if nome.startswith(pre) and len(nome) - len(pre) >= 3:
            return nome[len(pre):]
    return nome


def encurtar_todos_os_nomes():
    """Varre TODAS as competições cadastradas e grava no arquivo global uma
    versão curta de cada time/estádio que ainda não tem nome definido.
    Nunca sobrescreve o que você já ajustou. Retorna (times, estadios), cada
    um um dict {nome do Sofascore: nome curto} só com o que foi acrescentado."""
    todas = carregar_competicoes()          # já migra os nomes antigos
    g = carregar_nomes_globais()
    times, estadios = set(), set()
    for cfg in todas.values():
        times |= set(cfg.get("times_sofascore") or [])
        estadios |= set(cfg.get("estadios_sofascore") or [])
    novos_t = {n: encurtar_time(n) for n in times if n not in g["times"]}
    novos_e = {n: encurtar_estadio(n) for n in estadios if n not in g["estadios"]}
    novos_t = {k: v for k, v in novos_t.items() if v and v != k}
    novos_e = {k: v for k, v in novos_e.items() if v and v != k}
    atualizar_nomes_globais(novos_t, novos_e, sobrescrever=False)
    return novos_t, novos_e


def listar_nomes_da_temporada(tid, sid, pausa=0.3):
    """Nomes dos times (tabela) e dos estádios (estádio de cada time), como
    o Sofascore escreve. Serve para montar o painel de ajuste de nomes."""
    tabela = get(f"/unique-tournament/{tid}/season/{sid}/standings/total")
    linhas = [r for g in tabela["standings"] for r in g["rows"]]
    times, estadios = set(), set()
    for r in linhas:
        t = r["team"]
        times.add(t["name"])
        try:
            det = get(f"/team/{t['id']}").get("team", {})
            v = det.get("venue") or {}
            nome = (v.get("stadium") or {}).get("name") or v.get("name")
            if nome:
                estadios.add(nome)
        except Exception as e:  # noqa
            print(f"  (sem estádio de {t['name']}: {e})")
        time.sleep(pausa)
    return {"times": sorted(times, key=str.lower),
            "estadios": sorted(estadios, key=str.lower)}


def listar_nomes():
    """Mesma lista, para a competição em uso (depois de aplicar_competicao),
    mais as rodadas/fases da temporada."""
    dados = listar_nomes_da_temporada(TOURNAMENT_ID, SEASON_ID)
    try:
        rodadas, _atual = listar_rodadas(TOURNAMENT_ID, SEASON_ID)
        dados["rodadas"] = rodadas
        dados["mata_mata"] = any(r["slug"] for r in rodadas)
    except Exception as e:  # noqa
        print(f"  (não consegui listar as rodadas: {e})")
    return dados


def dados_pelo_link(url):
    """Lê o link de uma competição do Sofascore e devolve os dados básicos."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Cole o link da competição do Sofascore.")
    sem_extra = re.split(r"[#?]", url)[0]
    numeros = re.findall(r"/(\d+)(?=/|$)", sem_extra)
    if not numeros:
        raise ValueError("Não achei o número da competição no link. Use o link da "
                         "página do campeonato (ele termina com um número).")
    tid = int(numeros[-1])
    m = re.search(r"#id:(\d+)", url)
    sid_link = int(m.group(1)) if m else None

    info = get(f"/unique-tournament/{tid}").get("uniqueTournament") or {}
    temporadas = get(f"/unique-tournament/{tid}/seasons").get("seasons", [])
    if not temporadas:
        raise RuntimeError("O Sofascore não devolveu temporadas para esse link. "
                           "Confira se é o link de um campeonato.")
    esc = next((s for s in temporadas if s.get("id") == sid_link), temporadas[0])
    ano_txt = str(esc.get("year") or esc.get("name") or "")
    rodadas, total, mata_mata = [], None, False
    try:
        rodadas, _atual = listar_rodadas(tid, int(esc["id"]))
        numericas = [r["round"] for r in rodadas if not r["slug"]]
        total = max(numericas) if numericas else (len(rodadas) or None)
        mata_mata = any(r["slug"] for r in rodadas)
    except Exception as e:  # noqa
        print(f"  (não consegui listar as rodadas: {e})")
    cores = [info[k] for k in ("primaryColorHex", "secondaryColorHex")
             if re.fullmatch(r"#[0-9a-fA-F]{6}", str(info.get(k) or ""))]
    nomes = {"times": [], "estadios": []}
    try:
        nomes = listar_nomes_da_temporada(tid, int(esc["id"]))
    except Exception as e:  # noqa
        print(f"  (não consegui listar times e estádios: {e})")
    return {
        "times": nomes["times"], "estadios": nomes["estadios"],
        "nome": info.get("name") or f"Competição {tid}",
        "pais": (info.get("category") or {}).get("name", ""),
        "tournament_id": tid,
        "season_id": int(esc["id"]),
        "temporada": ano_txt,
        "ano_civil": "/" not in ano_txt,
        "total_rodadas": total,
        "rodadas": rodadas, "mata_mata": mata_mata,
        "cores": cores,
    }


def cfg_inicial_do_link(d):
    cores = (d.get("cores") or [])[:3]
    return {
        "nome": d["nome"], "nome_curto": d["nome"],
        "tournament_id": d["tournament_id"], "season_id": d["season_id"],
        "season_auto": True, "ano_civil": d["ano_civil"], "idioma": "pt",
        "cores": cores or list(PADROES_COMPETICAO["cores"]),
        "total_rodadas": d.get("total_rodadas") or 60,
        "rodadas": d.get("rodadas") or [], "mata_mata": bool(d.get("mata_mata")),
        "times_sofascore": d.get("times") or [],
        "estadios_sofascore": d.get("estadios") or [],
        # sugestão: nomes sem siglas (FC, SC, SV...); dá para editar no painel
        "nomes_times": {n: encurtar_time(n) for n in (d.get("times") or [])
                        if encurtar_time(n) != n},
        "nomes_estadios": {n: encurtar_estadio(n) for n in (d.get("estadios") or [])
                           if encurtar_estadio(n) != n},
    }


# --------------------------------------------------------------------------
# REQUISIÇÕES
# --------------------------------------------------------------------------
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # fallback (o Sofascore costuma bloquear)
    import requests as http
    _IMPERSONATE = {}


BASES = ["https://api.sofascore.com/api/v1",
         "https://www.sofascore.com/api/v1"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_usar_browser = False
_pw = {}


def _iniciar_browser():
    """Abre (uma vez) um Chromium de verdade na página do Sofascore."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "O Sofascore bloqueou (403) o acesso direto. Instale o navegador "
            "automatizado:\n    pip install playwright\n"
            "    playwright install chromium\ne rode de novo.")
    if "page" not in _pw:
        pw = sync_playwright().start()
        navegador = pw.chromium.launch(headless=True)
        ctx = navegador.new_context(locale="pt-BR", user_agent=UA)
        page = ctx.new_page()
        page.goto("https://www.sofascore.com/pt/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        _pw.update(pw=pw, navegador=navegador, page=page)


def _get_browser(caminho):
    """Plano B: faz a consulta de dentro do site do Sofascore (o
    navegador real passa pelo bloqueio)."""
    _iniciar_browser()
    js = ("async u => { const r = await fetch(u, {credentials: 'include'});"
          " return {s: r.status, t: await r.text()}; }")
    ultimo = None
    for base in BASES:
        res = _pw["page"].evaluate(js, base + caminho)
        if res["s"] == 200:
            return json.loads(res["t"])
        ultimo = res["s"]
    raise RuntimeError(f"HTTP {ultimo} mesmo pelo navegador")


def fechar_browser():
    if "navegador" in _pw:
        try:
            _pw["navegador"].close()
            _pw["pw"].stop()
        except Exception:  # noqa
            pass


def get(caminho, debug_nome=None, debug_dir=None):
    global _usar_browser
    dados, erro = None, None

    if not _usar_browser:
        hdr = dict(HEADERS)
        if not _IMPERSONATE:
            hdr["User-Agent"] = UA
        for base in BASES:
            try:
                r = http.get(base + caminho, headers=hdr, timeout=25,
                             **_IMPERSONATE)
                if r.status_code == 200:
                    dados = r.json()
                    break
                erro = f"HTTP {r.status_code}"
            except Exception as e:  # noqa
                erro = str(e)
        if dados is None:
            print(f"  (acesso direto falhou: {erro}; tentando pelo navegador)")
            _usar_browser = True

    if dados is None:
        dados = _get_browser(caminho)

    if debug_nome and debug_dir:
        (debug_dir / f"{debug_nome}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados


# --------------------------------------------------------------------------
# RODADAS E FASES  (pontos corridos, fase de liga/grupos e mata-mata)
# --------------------------------------------------------------------------
# trechos em inglês (como o Sofascore escreve) -> português. A ordem importa.
FASES_PT = [
    ("round of 64", "32 avos de final"), ("round of 32", "16 avos de final"),
    ("round of 16", "Oitavas de final"),
    ("knockout phase play", "Playoffs"), ("knockout round play", "Playoffs"),
    ("play-off", "Playoffs"), ("playoff", "Playoffs"),
    ("quarterfinal", "Quartas de final"), ("quarter-final", "Quartas de final"),
    ("semifinal", "Semifinais"), ("semi-final", "Semifinais"),
    ("3rd place", "Disputa do 3º lugar"), ("third place", "Disputa do 3º lugar"),
    ("final", "Final"), ("promotion", "Promoção"),
]


def traduzir_fase(texto):
    """'Round of 16' -> 'Oitavas de final' (o que não conhece fica como está)."""
    t = (texto or "").strip()
    tl = t.lower()
    for trecho, pt in FASES_PT:
        if trecho in tl:
            return pt
    t = re.sub(r"(?i)\bqualification\b", "Qualificação", t)
    t = re.sub(r"(?i)\bpreliminary\b", "Preliminar", t)
    t = re.sub(r"(?i)\bround\b", "Rodada", t)
    return t


def _spec(item):
    return {"round": int(item["round"]), "name": item.get("name") or "",
            "slug": item.get("slug") or "", "prefix": item.get("prefix") or ""}


def chave_rodada(spec):
    return f"{spec['round']}|{spec.get('slug', '')}|{spec.get('prefix', '')}"


def spec_da_chave(chave):
    p = (str(chave).split("|") + ["", ""])[:3]
    return {"round": int(p[0]), "name": "", "slug": p[1], "prefix": p[2]}


def pasta_rodada(spec):
    partes = [f"rodada_{spec['round']}"]
    for k in ("slug", "prefix"):
        if spec.get(k):
            partes.append(re.sub(r"[^a-z0-9-]", "", str(spec[k]).lower()))
    return "-".join(partes)


def eh_mata_mata(spec):
    """Fases com nome (oitavas, quartas, final...) são eliminatórias."""
    return bool(spec.get("slug"))


def rotulo_rodada(spec):
    """Texto para o painel e o título: 'Rodada 10' ou 'Oitavas de final'."""
    if spec.get("slug"):
        base = traduzir_fase(spec.get("name") or spec["slug"].replace("-", " "))
        if spec.get("prefix"):
            base = f"{traduzir_fase(spec['prefix'])} - {base}"
        return base
    return CFG["formato_rodada"].format(n=spec["round"],
                                        rotulo=CFG["rotulo_rodada"])


def caminho_eventos(spec):
    c = (f"/unique-tournament/{TOURNAMENT_ID}/season/{SEASON_ID}"
         f"/events/round/{spec['round']}")
    if spec.get("slug"):
        c += f"/slug/{spec['slug']}"
    if spec.get("prefix"):
        c += f"/prefix/{spec['prefix']}"
    return c


def listar_rodadas(tid, sid, debug_dir=None):
    """(todas as rodadas/fases em ordem, rodada atual ou None)."""
    info = get(f"/unique-tournament/{tid}/season/{sid}/rounds", "rodadas",
               debug_dir)
    todas = [_spec(r) for r in info.get("rounds", [])
             if isinstance(r.get("round"), int)]
    atual = None
    if info.get("currentRound") and isinstance(
            info["currentRound"].get("round"), int):
        atual = _spec(info["currentRound"])
    return todas, atual


def descobrir_rodada(debug_dir=None):
    """Descobre a próxima rodada/fase a ser jogada (ou a que está em andamento)."""
    base = f"/unique-tournament/{TOURNAMENT_ID}/season/{SEASON_ID}"
    try:
        todas, atual = listar_rodadas(TOURNAMENT_ID, SEASON_ID, debug_dir)
        if atual is None:
            raise RuntimeError("o Sofascore não informou a rodada atual")
        eventos = get(caminho_eventos(atual)).get("events", [])
        # se a rodada "atual" já terminou por completo, a próxima é a seguinte
        if eventos and all(e.get("status", {}).get("type") == "finished"
                           for e in eventos):
            chaves = [chave_rodada(s) for s in todas]
            ck = chave_rodada(atual)
            if ck in chaves:
                i = chaves.index(ck)
                if i < len(chaves) - 1:
                    atual = todas[i + 1]
            else:
                atual = {**atual, "round": atual["round"] + 1}
        return atual
    except Exception as e:  # noqa
        print(f"  (não consegui ler a rodada atual: {e}; usando a tabela)")
        tabela = get(f"{base}/standings/total")
        rows = [r for g in tabela["standings"] for r in g["rows"]]
        n = max(r.get("matches", 0) for r in rows) + 1
        return {"round": n, "name": "", "slug": "", "prefix": ""}


# --------------------------------------------------------------------------
# AGENDA
# --------------------------------------------------------------------------
def carregar_transmissoes():
    if ARQ_TRANSMISSOES.exists():
        return json.loads(ARQ_TRANSMISSOES.read_text(encoding="utf-8"))
    return {}


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def _busca_nome(mapa, nome):
    if nome in mapa:
        return mapa[nome]
    alvo = _norm(nome)
    for k, v in mapa.items():
        if _norm(k) == alvo:
            return v
    return None


def nome_time(nome):
    return _busca_nome(NOMES_TIMES, nome) or nome


PREFIXO_ESTADIO = "Stadio "


def nome_estadio(nome):
    achado = _busca_nome(NOMES_ESTADIOS, nome)
    if achado:
        return achado
    if PREFIXO_ESTADIO and nome.startswith(PREFIXO_ESTADIO):
        return nome[len(PREFIXO_ESTADIO):]
    return nome


# --------------------------------------------------------------------------
# TRANSMISSÕES (futnatv.net)
# --------------------------------------------------------------------------
FUTNATV = "https://futnatv.net"
CAMPEONATO_ALVO = "Campeonato Italiano"   # exatamente como aparece no site
MESES_PT = {"JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "ABRIL": 4, "MAIO": 5,
            "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9,
            "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}
# Como o site escreve -> como você quer escrever
CANAIS_SUBST = {"CazéTV": "CazeTV", "Caze TV": "CazeTV", "Canal GOAT": "GOAT",
                "ESPN Brasil": "ESPN Brasil (Youtube)"}


class _Texto(HTMLParser):
    """Transforma o HTML numa lista de textos, na ordem em que aparecem."""

    def __init__(self):
        super().__init__()
        self.linhas, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = " ".join(data.split())
            if t:
                self.linhas.append(t)


def _chave(nome):
    """Normaliza nome de time para comparar Sofascore x futnatv."""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    ignorar = {"fc", "ac", "as", "ssc", "us", "acf", "calcio", "hellas"}
    s = " ".join(p for p in s.split() if p not in ignorar)
    return {"inter": "internazionale", "inter milan": "internazionale"}.get(s, s)


_RE_GLOBO_PAREN = re.compile(r"(?i)\b(globo)\s*\([^)]*(?:\)|$)")


def limpar_transmissao(texto):
    """'Globo (RJ, MG e parte da rede) e Premiere' -> 'Globo e Premiere'.
    O parêntese da Globo só diz as praças/parte da rede: o canal é a Globo."""
    return _RE_GLOBO_PAREN.sub(r"\1", texto or "")


def _dividir_canais(texto):
    """Separa os canais por vírgula ou ' e ', mas só FORA dos parênteses."""
    partes, atual, nivel, i = [], "", 0, 0
    while i < len(texto):
        c = texto[i]
        if c == "(":
            nivel += 1
        elif c == ")":
            nivel = max(0, nivel - 1)
        if nivel == 0:
            if c == ",":
                partes.append(atual)
                atual, i = "", i + 1
                continue
            if texto[i:i + 3] == " e ":
                partes.append(atual)
                atual, i = "", i + 3
                continue
        atual += c
        i += 1
    partes.append(atual)
    return [p.strip() for p in partes if p.strip()]


def normalizar_canais(texto):
    """'ESPN 4 e YouTube (SportyNet)' -> 'ESPN4 e SportyNet'.
    'Globo (RJ, MG e parte da rede) e Premiere' -> 'Globo e Premiere'.
    'YouTube (TNT Sports)' -> 'TNT Sports (Youtube)' (selo com o ícone)."""
    saida = []
    for p in _dividir_canais(limpar_transmissao(texto)):
        m = re.fullmatch(r"(?i)(?:youtube|yt) \((.+)\)", p) \
            or re.fullmatch(r"(?i)(?:youtube|yt) (tnt(?: sports?)?)", p) \
            or re.fullmatch(r"(?i)(tnt(?: sports?)?) \((?:youtube|yt)\)", p)
        if m:
            p = m.group(1).strip()
            if _chave_canal(p) in ("tnt", "tntsport", "tntsports"):
                p = "TNT Sports (Youtube)"
        if not re.search(r"\w", p):   # sobras de leitura, como "<>"
            continue
        p = re.sub(r"^ESPN (\d)$", r"ESPN\1", p)
        p = CANAIS_SUBST.get(p, p)
        if p not in saida:
            saida.append(p)
    if len(saida) <= 1:
        return "".join(saida)
    return ", ".join(saida[:-1]) + " e " + saida[-1]


# Plataformas de streaming PAGAS (chave = nome só com letras e números). Elas
# só aparecem quando são a única transmissão do jogo; se houver TV ou YouTube,
# ficam de fora, a menos que o jogo esteja marcado com "tv_streamings" no painel.
# Premiere é canal de TV: sempre aparece, e sempre no fim da lista.
STREAMINGS_PAGOS = {
    "disney", "disneyplus", "star", "starplus", "max", "hbomax", "primevideo",
    "amazonprimevideo", "amazon", "paramount", "paramountplus", "appletv",
    "appletvplus", "netflix", "dazn", "globoplay",
}


def _juntar_canais(canais):
    if len(canais) <= 1:
        return "".join(canais)
    return ", ".join(canais[:-1]) + " e " + canais[-1]


def transmissao_exibida(j, mostrar_streamings=None):
    """Texto da transmissão como deve aparecer na agenda (imagem e fórum).
    j = jogo (dict) ou o texto bruto. Streamings pagos saem quando há outro
    canal, a não ser que o jogo peça para mostrá-los; Premiere vai pro fim."""
    if isinstance(j, str):
        texto, mostrar = j, bool(mostrar_streamings)
    else:
        texto = j.get("tv", "")
        mostrar = bool(j.get("tv_streamings") if mostrar_streamings is None
                       else mostrar_streamings)
    canais = _dividir_canais(limpar_transmissao(texto))
    if not canais:
        return ""
    gratis = [c for c in canais if _chave_canal(c) not in STREAMINGS_PAGOS]
    lista = canais if (mostrar or not gratis) else gratis
    premiere = [c for c in lista if _chave_canal(c) == "premiere"]
    return _juntar_canais([c for c in lista if c not in premiere] + premiere)


_ROTULO_RODADA = re.compile(
    r"(?i)\brodada\b|^(fase|oitavas|quartas|semifinais?|final|grupo|jogo|ida|"
    r"volta)\b")
LIMIAR_NOME = 0.6      # semelhança mínima entre dois nomes de time


def ler_pagina_futnatv(html):
    """Retorna (data_da_pagina, [(campeonato, hora, mandante, visitante,
    canais_brutos)]) com TODOS os jogos da página."""
    p = _Texto()
    p.feed(html)
    L = p.linhas

    data = None
    for l in L:
        m = re.search(r"(\d{1,2}) DE ([^\W\d_]+) DE (\d{4})", l.upper())
        if m and m.group(2) in MESES_PT:
            data = date(int(m.group(3)), MESES_PT[m.group(2)], int(m.group(1)))
            break

    jogos = []
    for i, l in enumerate(L):
        if not re.fullmatch(r"\d{1,2}h\d{2}", l):
            continue
        if i < 2 or i + 4 >= len(L) or L[i + 2].lower() != "x":
            continue
        # o campeonato fica 1 ou 2 linhas acima do horário (a outra é a rodada)
        acima = [re.sub(r"^[^\w\u00C0-\u00FF]+", "", L[k]) for k in (i - 1, i - 2)]
        camp = next((t for t in acima if not _ROTULO_RODADA.search(t)), acima[0])
        jogos.append((camp, l, L[i + 1], L[i + 3], L[i + 4]))
    return data, jogos


def ler_paginas_futnatv(jogos):
    """Lê as páginas do futnatv (janela de ±7 dias a partir de hoje).
    Retorna {data: [jogos da página]}."""
    hoje = datetime.now(FUSO).date()
    paginas = {}
    for d in sorted({j["inicio"].date() for j in jogos}):
        off = (d - hoje).days
        if abs(off) > 7:
            print(f"  aviso: {d} fora da janela de 7 dias do futnatv; "
                  f"rode de novo mais perto da rodada.")
            continue
        caminho = {0: "/", 1: "/amanha", -1: "/ontem"}.get(off, f"/d{off}")
        try:
            r = http.get(FUTNATV + caminho, timeout=25, **_IMPERSONATE)
            data, lista = ler_pagina_futnatv(r.text)
        except Exception as e:  # noqa
            print(f"  aviso: falha ao ler futnatv{caminho} ({e})")
            continue
        if data != d:
            print(f"  aviso: futnatv{caminho} trouxe a data {data}, "
                  f"esperado {d} (página em cache?)")
        paginas[data or d] = lista
        time.sleep(0.5)
    return paginas


def _similaridade(a, b):
    """0 a 1: o quanto dois nomes de time parecem ser o mesmo clube.
    Cobre 'Real Betis' x 'Bétis' e 'Tottenham Hotspur' x 'Tottenham'."""
    ka, kb = _chave(nome_time(a)), _chave(nome_time(b))
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ta, tb = set(ka.split()), set(kb.split())
    if ta <= tb or tb <= ta:       # um nome está dentro do outro
        return 0.9
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def _pontuacao_jogo(mand, vis, hora, j):
    """Quanto o jogo do futnatv parece o jogo j do Sofascore (0 = não é)."""
    sm = _similaridade(mand, j["mandante"])
    sv = _similaridade(vis, j["visitante"])
    mesma_hora = hora == j["hora"]
    if min(sm, sv) >= LIMIAR_NOME or (max(sm, sv) >= 0.9 and mesma_hora):
        return sm + sv + (0.5 if mesma_hora else 0)
    return 0.0


def _salvar_futnatv_detectado(nome):
    """Guarda no cadastro o nome do campeonato achado no futnatv."""
    if not SLUG_ATUAL:
        return
    try:
        todas = carregar_competicoes()
        if SLUG_ATUAL in todas and todas[SLUG_ATUAL].get("futnatv_auto") != nome:
            todas[SLUG_ATUAL]["futnatv_auto"] = nome
            _gravar_competicoes(todas)
    except Exception:  # noqa
        pass


def escolher_campeonato_futnatv(jogos, paginas):
    """Descobre como o futnatv chama esta competição: o campeonato cujos jogos
    batem com os da rodada. Se o nome cadastrado existir no site, usa ele."""
    rotulos = {x[0] for lista in paginas.values() for x in lista}
    placar = {}
    for d, lista in paginas.items():
        meus = [j for j in jogos if j["inicio"].date() == d]
        for camp, hora, mand, vis, _canal in lista:
            if any(_pontuacao_jogo(mand, vis, hora, j) for j in meus):
                placar[camp] = placar.get(camp, 0) + 1
    detectado = max(placar, key=placar.get) if placar else None

    if CAMPEONATO_ALVO and CAMPEONATO_ALVO in rotulos:
        return CAMPEONATO_ALVO
    if detectado:
        if CAMPEONATO_ALVO:
            print(f"  aviso: '{CAMPEONATO_ALVO}' não aparece no futnatv; "
                  f"usando '{detectado}', que bate com os jogos da rodada.")
        else:
            print(f"  campeonato identificado no futnatv: '{detectado}'")
        _salvar_futnatv_detectado(detectado)
        return detectado
    print("  aviso: não consegui identificar o campeonato no futnatv "
          "(jogos fora da janela de 7 dias?).")
    return None


def casar_transmissoes(jogos, paginas, campeonato):
    """Liga cada jogo do Sofascore ao do futnatv (por nomes parecidos e
    horário). Retorna {índice do jogo: canais brutos}."""
    resultado = {}
    for d, lista in paginas.items():
        fut = [x for x in lista if x[0] == campeonato]
        meus = [(i, j) for i, j in enumerate(jogos)
                if j["inicio"].date() == d and not j["tv_manual"]]
        pares = []
        for fi, (_c, hora, mand, vis, _canal) in enumerate(fut):
            for ji, (_i, j) in enumerate(meus):
                pont = _pontuacao_jogo(mand, vis, hora, j)
                if pont:
                    pares.append((pont, fi, ji))
        usados_f, usados_j = set(), set()
        for pont, fi, ji in sorted(pares, reverse=True):
            if fi in usados_f or ji in usados_j:
                continue
            usados_f.add(fi)
            usados_j.add(ji)
            resultado[meus[ji][0]] = fut[fi][4]

        # sobras: se no mesmo horário sobrou um jogo de cada lado, são o mesmo
        sobra_f = [fi for fi in range(len(fut)) if fi not in usados_f]
        sobra_j = [ji for ji in range(len(meus)) if ji not in usados_j]
        for fi in sobra_f:
            iguais_f = [x for x in sobra_f if fut[x][1] == fut[fi][1]]
            iguais_j = [ji for ji in sobra_j if meus[ji][1]["hora"] == fut[fi][1]]
            if len(iguais_f) == 1 and len(iguais_j) == 1:
                ji = iguais_j[0]
                resultado[meus[ji][0]] = fut[fi][4]
                usados_j.add(ji)
                j = meus[ji][1]
                print(f"  casado só pelo horário: {j['confronto']} = "
                      f"{fut[fi][2]} x {fut[fi][3]} (futnatv)")
    return resultado


def montar_agenda(rodada, debug_dir=None, usar_site=True):
    dados = get(caminho_eventos(rodada), "eventos_rodada", debug_dir)
    eventos = sorted(dados.get("events", []), key=lambda e: e["startTimestamp"])
    if not eventos:
        raise RuntimeError("Nenhum jogo encontrado para essa rodada.")

    tv_manual = carregar_transmissoes()
    jogos = []
    for ev in eventos:
        time.sleep(0.4)  # educação com o servidor
        try:
            det = get(f"/event/{ev['id']}")["event"]
        except Exception as e:  # noqa
            print(f"  aviso: sem detalhes do jogo {ev['id']} ({e})")
            det = ev

        inicio = datetime.fromtimestamp(ev["startTimestamp"], FUSO)
        mandante = nome_time(ev["homeTeam"]["name"])
        visitante = nome_time(ev["awayTeam"]["name"])
        estadio = (det.get("venue", {}).get("stadium", {}).get("name")
                   or det.get("venue", {}).get("name") or "A definir")
        confronto = f"{mandante} x {visitante}"
        manual = tv_manual.get(confronto)

        jogos.append({
            "inicio": inicio,
            "hora": f"{inicio.hour:02d}h{inicio.minute:02d}",
            "mandante": mandante,
            "visitante": visitante,
            "mandante_id": ev["homeTeam"].get("id"),
            "visitante_id": ev["awayTeam"].get("id"),
            "confronto": confronto,
            "estadio": nome_estadio(estadio),
            "tv": manual or TV_PADRAO,
            "tv_manual": bool(manual),
        })

    if usar_site:
        print("Buscando transmissões no futnatv...")
        paginas = ler_paginas_futnatv(jogos)
        campeonato = escolher_campeonato_futnatv(jogos, paginas)
        casadas = casar_transmissoes(jogos, paginas, campeonato) \
            if campeonato else {}
        for i, j in enumerate(jogos):
            if j["tv_manual"]:
                continue
            bruto = casadas.get(i)
            if bruto:
                j["tv"] = normalizar_canais(bruto)
            elif campeonato:
                print(f"  sem transmissão no futnatv: {j['confronto']} "
                      f"(usando '{TV_PADRAO}')")
    return jogos


def titulo_topico(rodada, jogos):
    """Ex.: 'Série A Enilive 2026/27 - 10° Giornata' ou
    'Champions League 2026/27 - Oitavas de final'."""
    d = jogos[0]["inicio"]
    if CFG.get("ano_civil"):
        temporada = f"{d.year}"
    else:
        ano = d.year if d.month >= 7 else d.year - 1
        temporada = f"{ano}/{(ano + 1) % 100:02d}"
    return f"{TITULO_COMPETICAO} {temporada} - {rotulo_rodada(rodada)}"


# --------------------------------------------------------------------------
# EDIÇÕES DO PAINEL (ficam salvas em edicoes.json, na pasta da rodada)
# --------------------------------------------------------------------------
# Guarda só o que o usuário mudou: jogos em destaque (e rótulo), estádio e
# transmissão corrigidos, streamings pagos liberados e cores de fundo da imagem
# do jogo da rodada. jogos.json continua com os dados "puros" do Sofascore;
# gerar o tópico de novo não apaga as edições.
def carregar_edicoes(pasta):
    f = pasta / "edicoes.json"
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:  # noqa
        return {}


def salvar_edicoes(pasta, edicoes):
    f = pasta / "edicoes.json"
    if not edicoes:
        if f.exists():
            f.unlink()
        return
    texto = json.dumps(edicoes, ensure_ascii=False, indent=2)
    try:
        if f.exists() and f.read_text(encoding="utf-8") == texto:
            return                                  # nada mudou
    except Exception:  # noqa
        pass
    f.write_text(texto, encoding="utf-8")


def _cor_hex_valida(c):
    return isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c.strip()) \
        is not None


def aplicar_edicoes(jogos, edicoes):
    """Cópia dos jogos com as edições salvas aplicadas."""
    padrao = str(edicoes.get("_rotulo_padrao") or "").strip() \
        or DESTAQUE_ROTULO_PADRAO
    saida = []
    for j in jogos:
        j = dict(j)
        ed = edicoes.get(j.get("confronto"), {})
        for k in ("estadio", "tv"):
            if ed.get(k) is not None:
                j[k] = ed[k]
        j["destaque"] = bool(ed.get("destaque"))
        j["rotulo"] = str(ed.get("rotulo") or "")
        j["destaque_rotulo"] = j["rotulo"] or padrao
        j["tv_streamings"] = bool(ed.get("tv_streamings"))
        for k in ("cor_mandante", "cor_visitante"):
            j[k] = ed.get(k) if _cor_hex_valida(ed.get(k)) else ""
        saida.append(j)
    return saida


def montar_edicoes(jogos, base, rotulo_padrao=""):
    """Dicionário de edições a salvar. base = {confronto: {estadio, tv}} dos
    dados sem edição (só o que for diferente é guardado)."""
    ed = {}
    for j in jogos:
        b, e = base.get(j["confronto"], {}), {}
        for k in ("estadio", "tv"):
            if str(j.get(k, "")) != str(b.get(k, "")):
                e[k] = j[k]
        if j.get("destaque"):
            e["destaque"] = True
            if j.get("rotulo"):
                e["rotulo"] = j["rotulo"]
        if j.get("tv_streamings"):
            e["tv_streamings"] = True
        for k in ("cor_mandante", "cor_visitante"):
            if _cor_hex_valida(j.get(k)):
                e[k] = j[k]
        if e:
            ed[j["confronto"]] = e
    rp = (rotulo_padrao or "").strip()
    if rp and rp != DESTAQUE_ROTULO_PADRAO:
        ed["_rotulo_padrao"] = rp
    return ed


def formatar_agenda(jogos):
    linhas = []
    dia_atual = None
    hora_atual = None
    for j in jogos:
        d = j["inicio"].date()
        if d != dia_atual:
            if dia_atual is not None:
                linhas.append("")
            titulo = (f"🗓️ {DIAS[j['inicio'].weekday()]}, {d.day} "
                      f"{MESES[d.month]} {d.year}")
            linhas.append(titulo)
            linhas.append("")
            dia_atual, hora_atual = d, None
        elif j["hora"] != hora_atual:
            linhas.append("")  # linha em branco entre horários do mesmo dia
        hora_atual = j["hora"]
        linha = (f"{j['hora']} - {j['confronto']} | {j['estadio']} | "
                 f"{transmissao_exibida(j)}")
        if j.get("destaque") and DESTAQUE_NO_TEXTO:
            linha += f" | ⭐ {rotulo_destaque(j)}"
        linhas.append(linha)
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------------
# ESTATÍSTICAS
# --------------------------------------------------------------------------
def top_jogadores(chave, dados):
    lista = dados.get("topPlayers", {}).get(chave, [])
    saida = []
    for item in lista[:TOP_N]:
        valor = item.get("statistics", {}).get(chave)
        if valor is None:
            continue
        saida.append((item["player"]["name"],
                      nome_time(item["team"]["name"]), valor,
                      item["player"].get("id"), item["team"].get("id")))
    return saida


MIN_JOGOS_GOLEIRO_PCT = 0.5   # goleiro precisa ter jogado ao menos 50% das rodadas


def _lista_goleiros(base, top, debug_dir=None):
    """Busca estatísticas de goleiros no Sofascore (tenta variações da consulta)."""
    tentativas = [
        f"{base}/statistics?limit=100&offset=0&order=-appearances"
        f"&accumulation=total&group=goalkeeper"
        f"&fields=goalsConceded,appearances,minutesPlayed"
        f"&filters=position.in.G",
        f"{base}/statistics?limit=100&offset=0&order=-appearances"
        f"&accumulation=total&fields=goalsConceded,appearances,minutesPlayed"
        f"&filters=position.in.G",
    ]
    for t in tentativas:
        try:
            dados = get(t, "goleiros", debug_dir)
            res = [r for r in dados.get("results", [])
                   if r.get("goalsConceded") is not None]
            if res:
                return res
        except Exception as e:  # noqa
            print(f"  (consulta de goleiros falhou: {e})")
    # plano B: alguma categoria do top-players com "conceded" no nome
    for chave, lista in (top.get("topPlayers") or {}).items():
        if "conceded" in chave.lower() and lista:
            return [{"player": i["player"], "team": i["team"],
                     "goalsConceded": i["statistics"].get("goalsConceded"),
                     "appearances": i["statistics"].get("appearances")}
                    for i in lista]
    raise RuntimeError("o Sofascore não devolveu estatísticas de goleiros")


def _goleiros_do_site(top, base, debug_dir=None):
    """Usa direto a lista 'Menos gols concedidos por jogo' do Sofascore."""
    fontes = [top]
    try:
        fontes.append(get(f"{base}/top-players/per-game",
                          "top_players_por_jogo", debug_dir))
    except Exception:  # noqa
        pass
    for fonte in fontes:
        for chave, lista in (fonte.get("topPlayers") or {}).items():
            k = chave.lower()
            if "conceded" in k and ("pergame" in k or "per_game" in k) and lista:
                linhas = []
                for i in lista:
                    st_ = i.get("statistics", {})
                    v = st_.get(chave)
                    if v is None:
                        continue
                    linhas.append((float(v), i["player"]["name"],
                                   nome_time(i["team"]["name"]),
                                   st_.get("appearances"),
                                   i["player"].get("id"), i["team"].get("id")))
                if linhas:
                    linhas.sort(key=lambda x: x[0])
                    return [(n, t + (f" • {a} jogos" if a else ""), f"{v:.2f}",
                             pid, tid)
                            for v, n, t, a, pid, tid in linhas[:TOP_N]]
    return None


def melhores_goleiros(res, jogadas):
    minimo = max(1, round(jogadas * MIN_JOGOS_GOLEIRO_PCT))
    lista = []
    for it in res:
        gs, ap = it.get("goalsConceded"), it.get("appearances")
        if gs is None or not ap or ap < minimo:
            continue
        lista.append((gs / ap, gs, ap, it["player"]["name"],
                      nome_time(it["team"]["name"]),
                      it["player"].get("id"), it["team"].get("id")))
    lista.sort(key=lambda x: (x[0], -x[2], x[3]))
    return [(nome, f"{time} • {gs} gols em {ap} jogos", f"{m:.2f}", pid, tid)
            for m, gs, ap, nome, time, pid, tid in lista[:TOP_N]]


# --------------------------------------------------------------------------
# IMAGENS
# --------------------------------------------------------------------------
def _fonte(tamanho, negrito=False):
    from PIL import ImageFont
    candidatas = (
        ["arialbd.ttf", "DejaVuSans-Bold.ttf", "Helvetica-Bold.ttf"]
        if negrito else ["arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"])
    for nome in candidatas:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


OURO = (255, 205, 60)


def _disco_suave(img, cx, cy, diam, cor, anel=0):
    """Círculo (cheio ou só o aro, se anel>0) com bordas suaves."""
    from PIL import Image, ImageDraw
    S = 4
    D = diam * S
    camada = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    dr = ImageDraw.Draw(camada)
    if anel:
        dr.ellipse([0, 0, D - 1, D - 1], outline=cor, width=anel * S)
    else:
        dr.ellipse([0, 0, D - 1, D - 1], fill=cor)
    camada = camada.resize((diam, diam), Image.LANCZOS)
    img.paste(camada, (int(cx - diam / 2), int(cy - diam / 2)), camada)


def _foto_jogador(player_id, nome, diam):
    """Foto do jogador recortada em círculo (ou as iniciais, se não houver)."""
    from PIL import Image, ImageDraw
    S = 3
    D = diam * S
    foto = _carregar_imagem("player", player_id) if player_id else None
    base = Image.new("RGBA", (D, D), _pal()["linha"] + (255,))
    if foto is not None:
        w, h = foto.size
        lado = min(w, h)
        x0 = (w - lado) // 2
        foto = foto.crop((x0, 0, x0 + lado, lado)).resize((D, D), Image.LANCZOS)
        base.alpha_composite(foto)
    else:
        iniciais = "".join(p[0] for p in str(nome).split()[:2]).upper() or "?"
        ImageDraw.Draw(base).text((D // 2, D // 2), iniciais,
                                  font=_fonte(int(D * 0.36), True),
                                  fill=_pal()["txt"] + (255,), anchor="mm")
    mascara = Image.new("L", (D, D), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, D - 1, D - 1], fill=255)
    saida = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    saida.paste(base, (0, 0), mascara)
    return saida.resize((diam, diam), Image.LANCZOS)


def _cartao_lider(img, d, lin, y0, alt, W, MARGEM):
    """Destaque do 1º colocado: foto em círculo, escudo do time e valor grande."""
    nome, detalhe, valor = lin[0], lin[1], lin[2]
    pid = lin[3] if len(lin) > 3 else None
    tid = lin[4] if len(lin) > 4 else None
    cy = y0 + alt // 2

    _caixa(img, [MARGEM - 20, y0 + 6, W - MARGEM + 20, y0 + alt - 6],
           _pal()["cartao"], 0.92, raio=20)
    d.rounded_rectangle([MARGEM - 20, y0 + 6, MARGEM - 12, y0 + alt - 6],
                        radius=4, fill=_pal()["ouro"])

    diam = 156
    cx = MARGEM + 100
    img.paste(_foto_jogador(pid, nome, diam),
              (int(cx - diam / 2), int(cy - diam / 2)),
              _foto_jogador(pid, nome, diam))
    _disco_suave(img, cx, cy, diam + 16, _pal()["ouro"] + (255,), anel=5)

    escudo = _carregar_escudo(tid) if tid else None
    if escudo is not None:       # escudo do time, pequeno, no canto da foto
        bx, by = cx + int(diam * 0.36), cy + int(diam * 0.36)
        _disco_suave(img, bx, by, 62, _pal()["bg"] + (255,))
        _colar_escudo(img, bx, by, 46, escudo)

    tx = MARGEM + 100 + diam // 2 + 44
    f_valor = _fonte(96, True)
    larg_valor = int(d.textlength(str(valor), font=f_valor))
    d.text((tx, cy - 56), "LÍDER", font=_fonte(22, True), fill=_pal()["ouro"],
           anchor="lm")
    f_nome = _fonte_ajustada(d, str(nome), W - MARGEM - tx - larg_valor - 40, 48)
    d.text((tx, cy - 10), str(nome), font=f_nome, fill=_pal()["txt"],
           anchor="lm")
    d.text((tx, cy + 38), str(detalhe), font=_fonte(26), fill=_pal()["suave"],
           anchor="lm")
    d.text((W - MARGEM, cy), str(valor), font=f_valor, fill=_pal()["ouro"], anchor="rm")


def gerar_imagem(titulo, subtitulo, cabecalho_valor, linhas, caminho):
    """Tabela de um ranking. O 1º colocado vem em destaque, com foto."""
    from PIL import Image, ImageDraw
    W, ALT_TOPO, ALT_LINHA, MARGEM, ALT_LIDER = 1080, 230, 84, 60, 230
    resto = linhas[1:]
    H = ALT_TOPO + ALT_LIDER + ALT_LINHA * len(resto) + 90

    img = Image.new("RGB", (W, H), _pal()["bg"])

    _textura_fundo(img)
    d = ImageDraw.Draw(img)

    _faixa_topo(d, W)

    xt, xs = _logo_cabecalho(img, MARGEM, 50, 50, 110, 162, "stats")
    d.text((xt, 50), titulo, font=_fonte(60, True), fill=_pal()["txt"])
    d.text((xs, 130), subtitulo, font=_fonte(30), fill=_pal()["suave"])
    d.text((W - MARGEM, 190), cabecalho_valor, font=_fonte(24, True),
           fill=_pal()["cab"], anchor="ra")

    if linhas:
        _cartao_lider(img, d, linhas[0], ALT_TOPO, ALT_LIDER, W, MARGEM)

    y = ALT_TOPO + ALT_LIDER
    for i, lin in enumerate(resto, start=2):
        nome, detalhe, valor = lin[0], lin[1], lin[2]
        if i % 2 == 0:
            _caixa(img, [MARGEM - 20, y, W - MARGEM + 20, y + ALT_LINHA - 6],
                   _pal()["linha_alt"], 0.70)
        d.text((MARGEM, y + ALT_LINHA // 2), f"{i}", font=_fonte(36, True),
               fill=_pal()["cab"], anchor="lm")
        d.text((MARGEM + 70, y + 26), str(nome)[:28], font=_fonte(34, True),
               fill=_pal()["txt"], anchor="lm")
        d.text((MARGEM + 70, y + 58), str(detalhe), font=_fonte(24),
               fill=_pal()["suave"], anchor="lm")
        d.text((W - MARGEM, y + ALT_LINHA // 2), str(valor),
               font=_fonte(44, True), fill=_pal()["txt"], anchor="rm")
        y += ALT_LINHA

    d.text((W // 2, H - 40), "Fonte: Sofascore", font=_fonte(22),
           fill=_pal()["rodape"], anchor="mm")
    img.save(caminho)


# --------------------------------------------------------------------------
# ESTATÍSTICAS FORMATO 2  (2 rankings por imagem, top 5 de cada)
# --------------------------------------------------------------------------
GERAR_FORMATO2_STATS = True      # False = não gera as estatísticas Formato 2
GERAR_STATS_INDIVIDUAIS = False   # True = também gera/mostra uma imagem para cada ranking
                                 # (gols, assistencias, defesas e notas); False = só as
                                 # imagens f2_stats (2 rankings por imagem)
F2_STATS_TOP = 8                # líder + até 9 linhas (cai p/ menos se ficar apertado)
F2_LINHA_MIN = 60                # altura mínima (px) de cada linha do ranking
F2_ROTULO_METRICA = {"NOTA": "DE MÉDIA"}    # texto ao lado do número do líder
F2_TAMANHO = (1500, 1200)        # largura x altura (5:4: mais comprida que a agenda)
F2_TOPO, F2_BASE = 160, 40


def _painel_stats_f2(img, d, x0, y0, x1, y1, painel):
    """Um ranking: cabeçalho, líder em destaque (com foto) e os demais."""
    pal = _pal()
    linhas = painel["linhas"][:F2_STATS_TOP]
    pw = x1 - x0
    PAD = 36
    _caixa(img, [x0, y0, x1, y1], pal["cartao"], 0.90, raio=22)

    # ---- cabeçalho do painel
    titulo = painel["titulo"].upper()
    d.text((x0 + PAD, y0 + 46), titulo,
           font=_fonte_ajustada(d, titulo, pw - 2 * PAD - 150, 26, minimo=20),
           fill=pal["txt"], anchor="lm")
    d.text((x1 - PAD, y0 + 46), painel["metrica"], font=_fonte(19, True),
           fill=pal["cab"], anchor="rm")
    d.line([x0 + PAD, y0 + 86, x1 - PAD, y0 + 86], fill=pal["linha"], width=2)

    # ---- líder
    nome, detalhe, valor = linhas[0][0], linhas[0][1], linhas[0][2]
    pid = linhas[0][3] if len(linhas[0]) > 3 else None
    tid = linhas[0][4] if len(linhas[0]) > 4 else None
    ouro = pal["ouro"]
    ly0, LH = y0 + 112, 262
    _caixa(img, [x0 + 20, ly0, x1 - 20, ly0 + LH], ouro, 0.09, raio=18)
    diam = 176
    fcx, fcy = x0 + PAD + 14 + diam // 2, ly0 + LH // 2
    foto = _foto_jogador(pid, nome, diam)
    img.paste(foto, (fcx - diam // 2, fcy - diam // 2), foto)
    _disco_suave(img, fcx, fcy, diam + 14, ouro + (255,), anel=4)
    if tid:                                   # escudo no canto da foto
        bx, by = fcx + int(diam * 0.37), fcy + int(diam * 0.37)
        _disco_suave(img, bx, by, 66, pal["cartao"] + (255,))
        desenhar_escudo(img, bx, by, 46, detalhe, tid)
    tx = fcx + diam // 2 + 38
    tw = x1 - PAD - tx
    d.text((tx, ly0 + 54), "LÍDER", font=_fonte(17, True), fill=ouro,
           anchor="lm")
    d.text((tx, ly0 + 98), str(nome),
           font=_fonte_ajustada(d, str(nome), tw, 34, minimo=22),
           fill=pal["txt"], anchor="lm")
    d.text((tx, ly0 + 134), str(detalhe),
           font=_fonte_ajustada(d, str(detalhe), tw, 23, negrito=False,
                                minimo=17),
           fill=pal["suave"], anchor="lm")
    rotulo = F2_ROTULO_METRICA.get(painel["metrica"], painel["metrica"])
    f_rot = _fonte(32, True)
    larg_rot = int(d.textlength(rotulo, font=f_rot))
    f_val = _fonte_ajustada(d, str(valor), tw - larg_rot - 18, 84, minimo=48)
    base_val = ly0 + 232                      # linha de base comum (número + rótulo)
    d.text((tx, base_val), str(valor), font=f_val, fill=ouro, anchor="ls")
    d.text((tx + int(d.textlength(str(valor), font=f_val)) + 18, base_val),
           rotulo, font=f_rot, fill=ouro, anchor="ls")

    # ---- 2º em diante: POSIÇÃO  ESCUDO  Nome (Time)  DADO, numa linha só
    ry0 = ly0 + LH + 22
    disponivel = y1 - 24 - ry0
    n_cabem = max(disponivel // F2_LINHA_MIN, 1)
    resto = linhas[1:min(F2_STATS_TOP, 1 + n_cabem)]
    rh = min(80, disponivel // max(len(resto), 1)) if resto else 0
    cinza = pal["suave"]
    for i, lin in enumerate(resto):
        n, det, val = lin[0], lin[1], lin[2]
        tid_i = lin[4] if len(lin) > 4 else None
        time = str(det).split(" • ")[0].strip()     # só o time (goleiros trazem + jogos)
        ry = ry0 + i * rh
        rcy = ry + rh // 2
        if i > 0:
            d.line([x0 + PAD, ry, x1 - PAD, ry], fill=pal["divisor"], width=2)
        d.text((x0 + PAD, rcy), str(i + 2), font=_fonte(28, True),
               fill=pal["cab"], anchor="lm")
        desenhar_escudo(img, x0 + PAD + 74, rcy, 46, time, tid_i)
        f_val = _fonte(40, True)
        lv = int(d.textlength(str(val), font=f_val))
        d.text((x1 - PAD, rcy), str(val), font=f_val, fill=pal["txt"],
               anchor="rm")
        xn = x0 + PAD + 112
        larg = x1 - PAD - lv - 24 - xn
        # nome em branco + (time) em cinza, mesma linha de base; encolhe até caber
        tam = 29
        while True:
            f_n, f_t = _fonte(tam, True), _fonte(max(14, round(tam * 0.80)))
            w_n = int(d.textlength(str(n), font=f_n))
            w_t = int(d.textlength(f" ({time})", font=f_t))
            if w_n + w_t <= larg or tam <= 17:
                break
            tam -= 1
        base = rcy + round(tam * 0.36)
        d.text((xn, base), str(n), font=f_n, fill=pal["txt"], anchor="ls")
        if w_n + w_t > larg:                       # ainda não coube: corta o time
            while time and w_n + w_t > larg:
                time = time[:-1]
                w_t = int(d.textlength(f" ({time}…)", font=f_t))
            texto_t = f" ({time}…)" if len(time) >= 3 else ""
        else:
            texto_t = f" ({time})"
        d.text((xn + w_n, base), texto_t, font=f_t, fill=cinza, anchor="ls")


def gerar_stats_f2(paineis, subtitulo, pasta):
    """f2_stats.png (ou f2_stats_1.png, f2_stats_2.png...): dois rankings por
    imagem (ex.: Artilheiros + Assistências; Goleiros + Notas médias)."""
    from PIL import Image, ImageDraw
    for velho in pasta.glob("f2_stats*.png"):
        try:
            velho.unlink()
        except OSError:
            pass
    validos = [p for p in paineis if p.get("linhas")]
    if not validos:
        return []
    W, H = F2_TAMANHO
    M, GAP = 36, 24
    pw = (W - 2 * M - GAP) // 2
    pal = _pal()
    grupos = [validos[i:i + 2] for i in range(0, len(validos), 2)]
    caminhos = []
    for n, grupo in enumerate(grupos, start=1):
        img = Image.new("RGB", (W, H), pal["bg"])
        _textura_fundo(img)
        d = ImageDraw.Draw(img)
        _faixa_topo(d, W)
        titulo = "Estatísticas Individuais"
        xt, xs = _logo_cabecalho(img, M + 10, 32, 76, 130, 138, "stats")
        d.text((xs, 36), subtitulo, font=_fonte(26), fill=pal["suave"])
        d.text((xt, 76), titulo,
               font=_fonte_ajustada(d, titulo, W - M - 10 - xt, 52),
               fill=pal["txt"])
        x_ini = M if len(grupo) == 2 else (W - pw) // 2
        for k, painel in enumerate(grupo):
            x0 = x_ini + k * (pw + GAP)
            _painel_stats_f2(img, d, x0, F2_TOPO, x0 + pw, H - F2_BASE, painel)
        nome = "f2_stats.png" if len(grupos) == 1 else f"f2_stats_{n}.png"
        img.save(pasta / nome)
        caminhos.append(pasta / nome)
    return caminhos


# --------------------------------------------------------------------------
# CLASSIFICAÇÃO (imagem com "botões" nas cores dos clubes)
# --------------------------------------------------------------------------
# Cores e legendas das zonas. As posições vêm do próprio Sofascore (campo
# "promotion" de cada linha da tabela). Se ele não informar nada, usa ZONAS_PADRAO.
CATEGORIAS = {
    "cl":  ((36, 112, 232), "Champions League"),
    "el":  ((245, 140, 30), "Europa League"),
    "ecl": ((40, 180, 110), "Conference League"),
    "rel": ((222, 52, 62), "Rebaixamento"),
}
ZONAS_PADRAO = {"cl": (1, 4), "el": (5, 5), "ecl": (6, 6), "rel": (18, 20)}

# chave do clube -> (sigla, estilo, cor1, cor2, cor do aro)
# estilos: "solid" (lisa), "stripes" (listras), "halves" (metade/metade)
CLUBES = {
    "milan":          ("MIL", "stripes", (200, 20, 40), (15, 15, 15), (15, 15, 15)),
    "internazionale": ("INT", "stripes", (20, 60, 160), (10, 10, 10), (10, 10, 10)),
    "juventus":       ("JUV", "stripes", (245, 245, 245), (15, 15, 15), (15, 15, 15)),
    "napoli":         ("NAP", "solid", (40, 150, 220), (255, 255, 255), (255, 255, 255)),
    "roma":           ("ROM", "solid", (150, 30, 50), (240, 190, 40), (240, 190, 40)),
    "lazio":          ("LAZ", "solid", (130, 200, 240), (255, 255, 255), (255, 255, 255)),
    "atalanta":       ("ATA", "stripes", (20, 20, 20), (20, 90, 180), (20, 90, 180)),
    "fiorentina":     ("FIO", "solid", (110, 50, 160), (255, 255, 255), (255, 255, 255)),
    "bologna":        ("BOL", "stripes", (190, 25, 45), (20, 45, 110), (20, 45, 110)),
    "torino":         ("TOR", "solid", (120, 25, 40), (255, 255, 255), (255, 255, 255)),
    "genoa":          ("GEN", "halves", (190, 25, 45), (20, 45, 110), (20, 45, 110)),
    "udinese":        ("UDI", "stripes", (245, 245, 245), (20, 20, 20), (20, 20, 20)),
    "cagliari":       ("CAG", "solid", (190, 25, 45), (20, 45, 110), (20, 45, 110)),
    "lecce":          ("LEC", "stripes", (250, 210, 30), (200, 25, 45), (200, 25, 45)),
    "parma":          ("PAR", "stripes", (250, 205, 30), (25, 85, 180), (25, 85, 180)),
    "como":           ("COM", "solid", (30, 90, 180), (255, 255, 255), (255, 255, 255)),
    "venezia":        ("VEN", "halves", (20, 20, 20), (30, 140, 70), (240, 120, 30)),
    "sassuolo":       ("SAS", "stripes", (20, 150, 70), (20, 20, 20), (20, 20, 20)),
    "monza":          ("MON", "stripes", (205, 25, 45), (250, 250, 250), (205, 25, 45)),
    "frosinone":      ("FRO", "stripes", (250, 210, 30), (30, 80, 170), (30, 80, 170)),
    "verona":         ("VER", "halves", (250, 210, 30), (20, 60, 150), (20, 60, 150)),
    "cremonese":      ("CRE", "stripes", (150, 150, 150), (200, 30, 45), (200, 30, 45)),
    "pisa":           ("PIS", "stripes", (20, 20, 20), (30, 90, 170), (30, 90, 170)),
    "palermo":        ("PAL", "solid", (240, 150, 170), (20, 20, 20), (20, 20, 20)),
}


def estilo_clube(nome):
    """Plano B (sem escudo real): cores do uniforme para clubes conhecidos."""
    chave = _chave(nome_time(nome))
    palavras = chave.split()
    for k, v in CLUBES.items():
        if chave == k or k in palavras:
            return v + (True,)
    sigla = re.sub(r"[^A-Z]", "", nome.upper())[:3] or "???"
    return (sigla, "solid", (110, 120, 140), (255, 255, 255), (255, 255, 255),
            False)


def _lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _cores_competicao():
    cores = CFG.get("cores") or PADROES_COMPETICAO["cores"]
    return [_hex_rgb(c) for c in cores]


def _faixa_topo(d, W):
    """Faixa colorida no topo, nas cores da competição."""
    cores = _cores_competicao()
    n = len(cores)
    for i, c in enumerate(cores):
        d.rectangle([i * W // n, 0, (i + 1) * W // n, 12], fill=c)


def _cor_destaque():
    return _cores_competicao()[0]


# --------------------------------------------------------------------------
# LOGO DA COMPETIÇÃO NO CABEÇALHO  (ligue/desligue ou troque o modo aqui)
# --------------------------------------------------------------------------
LOGO_CABECALHO = True          # False = sem logo em NENHUMA imagem (chave geral)
# "grande"  = logo na altura do cabeçalho inteiro (título + subtítulo),
#             todos os textos deslocados para a direita dele
# "pequeno" = logo do tamanho do título, só ao lado da linha do título;
#             o subtítulo continua alinhado à margem esquerda
LOGO_CABECALHO_MODO = "grande"
# "original" = cores do logo | "branco" = versão branca que mantém os
# detalhes | "auto" = original, mas vira branco se ele quase some no fundo
LOGO_CABECALHO_COR = "auto"

# Cada tipo de imagem tem o seu próprio liga/desliga, tamanho e cor, ajustados
# no painel (competição > "Logo no cabeçalho das imagens"):
LOGO_CAB_IMAGENS = {
    "agenda": "Agenda",
    "classificacao": "Classificação (e mata-mata)",
    "stats": "Estatísticas (gols, assistências, goleiros e notas)",
}
LOGO_CAB_TAMANHOS = {"grande": "Grande", "pequeno": "Pequeno"}
LOGO_CAB_CORES = {"auto": "Automático", "original": "Cores originais",
                  "branco": "Branco"}


def _opcoes_logo_cab(tipo):
    """(ligado, tamanho, cor) do logo no cabeçalho deste tipo de imagem."""
    ligado = bool(CFG.get(f"logo_cab_{tipo}", LOGO_CABECALHO))
    tam = str(CFG.get(f"logo_cab_{tipo}_tam") or LOGO_CABECALHO_MODO).lower()
    cor = str(CFG.get(f"logo_cab_{tipo}_cor") or LOGO_CABECALHO_COR).lower()
    return (ligado and LOGO_CABECALHO,
            tam if tam in LOGO_CAB_TAMANHOS else "grande",
            cor if cor in LOGO_CAB_CORES else "auto")


def _logo_branco(logo):
    """Versão branca do logo SEM virar uma mancha: o tom dominante fica branco
    sólido e os detalhes internos (partes mais claras ou mais escuras que o
    corpo do logo) ficam translúcidos, deixando o fundo aparecer. Se o logo
    tem uma cor só, sai a silhueta branca."""
    from PIL import Image, ImageChops
    a = logo.getchannel("A")
    branco = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    lum = logo.convert("L")
    px = sorted(l for l, al in zip(lum.getdata(), a.getdata()) if al > 200)
    if len(px) < 50:
        branco.putalpha(a)
        return branco
    n = len(px)
    lo, hi, med = px[int(n * 0.05)], px[int(n * 0.95)], px[n // 2]
    amp = hi - lo
    if amp < 28:                           # logo de uma cor só
        branco.putalpha(a)
        return branco
    FORCA = 0.50                           # 0 = silhueta | 1 = detalhes somem
    lut = [int(255 * (1 - FORCA * min(1.0, abs(v - med) / (amp * 0.5))))
           for v in range(256)]
    fator = lum.point(lut)
    # bordas suavizadas (alfa parcial) não entram na conta
    borda = a.point(lambda v: 255 if v < 250 else 0)
    fator = ImageChops.lighter(fator, borda)
    branco.putalpha(ImageChops.multiply(a, fator))
    return branco


def _logo_para_cabecalho(altura, cor=None):
    """Logo (RGBA) com a altura pedida, ou None."""
    from PIL import Image, ImageChops
    if not LOGO_CABECALHO or altura < 20:
        return None
    try:
        logo = _logo_competicao()
    except Exception:  # noqa
        logo = None
    if logo is None:
        return None
    logo = logo.convert("RGBA")
    a = logo.getchannel("A")
    if a.getextrema()[0] >= 250:           # sem transparência: usa o contraste
        g = logo.convert("L")
        a = ImageChops.difference(
            g, Image.new("L", g.size, g.getpixel((0, 0)))
        ).point(lambda v: min(255, v * 3))
        logo.putalpha(a)
    larg = max(1, round(logo.width * altura / logo.height))
    if larg > altura * 1.5:                # logo muito largo: limita
        larg, altura = round(altura * 1.5), round(altura * 1.5 * logo.height / logo.width)
    logo = logo.resize((larg, max(1, altura)), Image.LANCZOS)
    cor = str(cor or LOGO_CABECALHO_COR or "auto").lower()
    if cor == "auto":
        a = logo.getchannel("A")
        m = a.point(lambda v: 255 if v > 128 else 0)
        if m.getbbox():
            from PIL import ImageStat
            r, g_, b = ImageStat.Stat(logo.convert("RGB"), mask=m).mean[:3]
            cor = "branco" if abs(_lum((r, g_, b)) - _lum(_pal()["bg"])) < 0.22 \
                else "original"
        else:
            cor = "original"
    if cor == "branco":
        logo = _logo_branco(logo)
    return logo


def _logo_cabecalho(img, x, topo_cab, topo_tit, base_tit, base_cab,
                    tipo="agenda"):
    """Cola o logo da competição à esquerda do cabeçalho e devolve
    (x do título, x das demais linhas) já deslocados. Se o logo estiver
    desligado (para este tipo de imagem) ou não existir, devolve (x, x) e
    nada muda.
      topo_cab/base_cab = onde o cabeçalho inteiro começa/termina;
      topo_tit/base_tit = onde a linha do título começa/termina;
      tipo = 'agenda' | 'classificacao' | 'stats' (usa as opções do painel)."""
    ligado, tam, cor = _opcoes_logo_cab(tipo)
    if not ligado:
        return x, x
    grande = tam != "pequeno"
    if grande:
        logo = _logo_para_cabecalho(base_cab - topo_cab, cor)
    else:
        logo = _logo_para_cabecalho(int((base_tit - topo_tit) * 0.95), cor)
    if logo is None:
        return x, x
    if grande:
        y = topo_cab + ((base_cab - topo_cab) - logo.height) // 2
        gap = 24
    else:
        y = int(topo_tit + 0.55 * (base_tit - topo_tit) - logo.height / 2)
        gap = 16
    img.paste(logo, (x, y), logo)
    deslocado = x + logo.width + gap
    return (deslocado, deslocado) if grande else (deslocado, x)


# --------------------------------------------------------------------------
# PALETA DE FUNDO (derivada da cor da competição)
# --------------------------------------------------------------------------
# Antes o fundo era sempre azul-marinho. Agora a matiz vem da cor principal da
# competição (ou de uma cor escolhida no cadastro), e os tons (fundo, linhas
# alternadas, cartões, divisórias e textos apagados) são gerados a partir dela
# com as mesmas luminosidades do azul antigo.
_AZUL_ANTIGO = {
    "bg": (14, 20, 36), "zebra_jogo": (20, 29, 50), "linha_alt": (22, 31, 54),
    "cartao": (26, 38, 66), "linha": (40, 52, 82), "divisor": (36, 48, 76),
    "chave": (60, 75, 110), "suave": (150, 165, 195), "cab": (120, 135, 165),
    "rodape": (100, 115, 145),
}
# nível de luminosidade (0-1) de cada tom e quanto de saturação ele recebe
_NIVEIS_PALETA = {
    "bg": (0.075, 1.00), "zebra_jogo": (0.105, 1.00), "linha_alt": (0.120, 1.00),
    "cartao": (0.155, 1.00), "linha": (0.215, 0.95), "divisor": (0.195, 0.95),
    "chave": (0.300, 0.80), "suave": (0.700, 0.55), "cab": (0.585, 0.50),
    "rodape": (0.500, 0.45),
}
_paleta_cache = {}


def _matiz_da_competicao():
    """Matiz (0-1) e saturação base. Usa a cor escolhida em 'fundo' ou a
    primeira cor da competição que tenha cor de verdade (não branco/cinza)."""
    import colorsys
    fundo = str(CFG.get("fundo") or "").strip()
    candidatas = []
    if re.fullmatch(r"#[0-9a-fA-F]{6}", fundo):
        candidatas.append(fundo)
    candidatas += list(CFG.get("cores") or [])
    for c in candidatas:
        try:
            r, g, b = (x / 255 for x in _hex_rgb(c))
        except Exception:  # noqa
            continue
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        if s >= 0.30 and 0.12 <= l <= 0.88:
            return h, s
    return None


# Tons extras do tema escuro (texto, destaque, etc.)
_EXTRAS_ESCURO = {
    "txt": (255, 255, 255), "txt2": (200, 210, 230), "ouro": (255, 205, 60),
    "apagado": (110, 125, 155), "marca": (255, 255, 255),
}
# Tema claro: (luminosidade, fator de saturação) de cada tom.
_NIVEIS_CLARO = {
    "bg": (0.945, 1.00), "zebra_jogo": (0.920, 1.00), "linha_alt": (0.910, 1.00),
    "cartao": (0.880, 1.00), "linha": (0.790, 0.90), "divisor": (0.820, 0.90),
    "chave": (0.650, 0.80), "suave": (0.380, 0.55), "cab": (0.450, 0.50),
    "rodape": (0.520, 0.45), "txt": (0.130, 0.55), "txt2": (0.270, 0.50),
    "apagado": (0.640, 0.30), "marca": (0.200, 0.55),
}
# Tema meio-termo (padrão): fundo na cor da competição, nem claro nem escuro,
# com textos claros. Cartões e linhas alternadas ficam um pouco mais escuros.
_NIVEIS_MEDIO = {
    "bg": (0.400, 1.00), "zebra_jogo": (0.365, 1.00), "linha_alt": (0.345, 1.00),
    "cartao": (0.300, 1.00), "linha": (0.500, 0.90), "divisor": (0.470, 0.90),
    "chave": (0.560, 0.80), "suave": (0.860, 0.55), "cab": (0.800, 0.55),
    "rodape": (0.740, 0.45),
}


def _hls(h, lum, sat):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, lum, max(0.0, min(1.0, sat)))
    return (round(r * 255), round(g * 255), round(b * 255))


def _pal():
    """Tons do fundo da competição em uso (cache por configuração).
    Inclui 'modo' (o tema), os tons de texto/destaque e 'pad_a'/'pad_b'
    (claro e escuro do desenho geométrico do fundo)."""
    modo_fundo = str(CFG.get("fundo") or "").strip().lower()
    tema = str(CFG.get("tema") or "medio").lower()
    if tema not in ("claro", "escuro", "medio"):
        tema = "medio"
    chave = (modo_fundo, tema, tuple(CFG.get("cores") or []))
    if chave in _paleta_cache:
        return _paleta_cache[chave]
    azul = modo_fundo in ("azul", "padrao", "padrão")
    achado = (0.60, 0.70) if azul else _matiz_da_competicao()
    if tema == "escuro":
        if azul or achado is None:
            pal, h, bs = dict(_AZUL_ANTIGO), 0.62, 0.45
        else:
            h, s = achado
            bs = min(0.50, max(0.30, s * 0.55))   # fundo escuro, sem "gritar"
            pal = {nome: _hls(h, lum, bs * fator)
                   for nome, (lum, fator) in _NIVEIS_PALETA.items()}
        pal.update(_EXTRAS_ESCURO)
        pal["pad_a"] = _hls(h, 0.42, min(1.0, bs * 1.2))
        pal["pad_b"] = _hls(h, 0.03, bs)
    elif tema == "medio":
        h, s = achado or (0.58, 0.45)
        bs = min(0.58, max(0.38, s * 0.70))   # cor da competição, sem gritar
        pal = {nome: _hls(h, lum, bs * fator)
               for nome, (lum, fator) in _NIVEIS_MEDIO.items()}
        pal.update({"txt": (255, 255, 255), "txt2": _hls(h, 0.93, 0.60),
                    "ouro": (255, 224, 130), "apagado": _hls(h, 0.68, 0.35),
                    "marca": (255, 255, 255)})
        pal["pad_a"] = _hls(h, 0.68, bs * 0.90)
        pal["pad_b"] = _hls(h, 0.12, bs)
    else:
        h, s = achado or (0.58, 0.35)
        bs = min(0.90, max(0.45, s * 0.90))
        pal = {nome: _hls(h, lum, bs * fator)
               for nome, (lum, fator) in _NIVEIS_CLARO.items()}
        pal["ouro"] = (186, 118, 0)
        pal["pad_a"] = (255, 255, 255)
        pal["pad_b"] = _hls(h, 0.55, bs)
    pal["modo"] = tema
    _paleta_cache[chave] = pal
    return pal


# --------------------------------------------------------------------------
# ESCUDOS  (baixados do Sofascore uma vez e guardados na pasta "escudos")
# --------------------------------------------------------------------------
PASTA_ESCUDOS = PASTA_BASE / "escudos"
PASTA_FOTOS = PASTA_BASE / "fotos"
PASTA_LOGOS_COMP = PASTA_BASE / "logos_competicao"   # logo da competição
URLS_IMAGEM = [
    "https://img.sofascore.com/api/v1/{tipo}/{id}/image",
    "https://api.sofascore.app/api/v1/{tipo}/{id}/image",
    "https://api.sofascore.com/api/v1/{tipo}/{id}/image",
]
_imagens_mem = {}
_imagens_falha = set()
_escudos_so_cache = False      # o painel liga isto: só usa imagens já baixadas
_escudos_estado = {"falhas_diretas": 0, "navegador_ok": True}


def _imagem_valida(conteudo):
    try:
        from PIL import Image
        Image.open(io.BytesIO(conteudo)).verify()
        return True
    except Exception:  # noqa
        return False


def _bytes_pelo_navegador(url):
    _iniciar_browser()
    resp = _pw["page"].context.request.get(
        url, headers={"Referer": "https://www.sofascore.com/"}, timeout=25000)
    return resp.body() if resp.ok else None


def baixar_imagem(tipo, id_):
    """Baixa o escudo ('team') ou a foto ('player') do Sofascore, uma única
    vez, e guarda em disco. Retorna o caminho, ou None se não conseguir."""
    pasta = {"team": PASTA_ESCUDOS, "player": PASTA_FOTOS}.get(
        tipo, PASTA_LOGOS_COMP)
    arq = pasta / f"{id_}.png"
    if arq.exists() and arq.stat().st_size > 0:
        return arq
    chave = (tipo, id_)
    if _escudos_so_cache or chave in _imagens_falha:
        return None

    conteudo = None
    if _escudos_estado["falhas_diretas"] < 3:
        hdr = dict(HEADERS)
        if not _IMPERSONATE:
            hdr["User-Agent"] = UA
        for modelo in URLS_IMAGEM:
            try:
                r = http.get(modelo.format(tipo=tipo, id=id_), headers=hdr,
                             timeout=20, **_IMPERSONATE)
                if r.status_code == 200 and _imagem_valida(r.content):
                    conteudo = r.content
                    break
            except Exception:  # noqa
                pass
        if conteudo is None:
            _escudos_estado["falhas_diretas"] += 1
        else:
            _escudos_estado["falhas_diretas"] = 0

    if conteudo is None and _escudos_estado["navegador_ok"]:
        for modelo in URLS_IMAGEM:
            try:
                b = _bytes_pelo_navegador(modelo.format(tipo=tipo, id=id_))
            except Exception as e:  # noqa
                print(f"  (imagens pelo navegador indisponível: {e})")
                _escudos_estado["navegador_ok"] = False
                break
            if b and _imagem_valida(b):
                conteudo = b
                break

    if conteudo is None:
        _imagens_falha.add(chave)
        alvo = {"team": "escudo do time", "player": "foto do jogador"}.get(
            tipo, "logo da competição")
        destino = ("usando um desenho simples no lugar"
                   if tipo in ("team", "player")
                   else "as imagens saem sem o logo no fundo")
        print(f"  aviso: não consegui baixar o {alvo} {id_}; {destino}.")
        return None
    pasta.mkdir(parents=True, exist_ok=True)
    arq.write_bytes(conteudo)
    time.sleep(0.15)
    return arq


# --------------------------------------------------------------------------
# ESTRELAS DOS ESCUDOS  (removidas para o escudo ficar medido só pela parte útil)
# --------------------------------------------------------------------------
REMOVER_ESTRELAS = True        # False = mantém os escudos exatamente como vêm
IGUALAR_AREA_ESCUDOS = True    # reduz um pouco os escudos "gordos" (redondos) p/
                               # todos terem peso visual parecido; False = desliga
_LADO_ANALISE = 384            # resolução usada só para procurar as estrelas


def _componentes(mascara, w, h):
    """Blocos de pixels conectados (8 vizinhos) de uma máscara w*h (0/1).
    Cada bloco: lista de índices."""
    visto = bytearray(w * h)
    blocos = []
    for ini in range(w * h):
        if not mascara[ini] or visto[ini]:
            continue
        visto[ini] = 1
        pilha = [ini]
        pix = []
        while pilha:
            i = pilha.pop()
            pix.append(i)
            y, x = divmod(i, w)
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w:
                        j = yy * w + xx
                        if mascara[j] and not visto[j]:
                            visto[j] = 1
                            pilha.append(j)
        blocos.append(pix)
    return blocos


def _geometria(pix, w):
    xs = [i % w for i in pix]
    ys = [i // w for i in pix]
    return (min(xs), min(ys), max(xs), max(ys),
            sum(xs) / len(xs), sum(ys) / len(ys))


def _eh_estrela(pix, w):
    """True SÓ se o bloco tiver o formato de uma estrela de 5 pontas: perfil
    radial com exatamente 5 picos igualmente espaçados (72 graus), proporção
    quase quadrada e preenchimento compatível. Coroas, letras, bolas, flores
    etc. não passam nesse teste."""
    import math
    if len(pix) < 40:
        return False
    x0, y0, x1, y1, mx, my = _geometria(pix, w)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if not 0.75 <= bw / bh <= 1.33:
        return False
    N = 72
    rmax = [0.0] * N
    rbruto = 0.0
    for i in pix:
        dx, dy = i % w - mx, i // w - my
        d = math.hypot(dx, dy)
        rbruto = max(rbruto, d)
        b = int((math.atan2(dy, dx) + math.pi) / (2 * math.pi) * N) % N
        if d > rmax[b]:
            rmax[b] = d
    if rbruto < 6 or sum(1 for v in rmax if v > 0) < N * 0.9:
        return False
    # preenchimento: estrela cheia de 5 pontas ocupa ~0,36 do círculo
    if not 0.22 <= len(pix) / (math.pi * rbruto ** 2) <= 0.60:
        return False
    s = [(rmax[i - 1] + rmax[i] + rmax[(i + 1) % N]) / 3 for i in range(N)]
    alto, baixo = max(s), min(s)
    if baixo / alto > 0.78:              # quase um círculo: não é estrela
        return False
    limiar = baixo + 0.35 * (alto - baixo)
    picos = []
    for i in range(N):
        janela = [s[(i + k) % N] for k in range(-5, 6)]
        if s[i] >= limiar and s[i] == max(janela) and \
                s[i] > max(s[(i - 1) % N], s[(i + 1) % N]) - 1e-9:
            if not picos or (i - picos[-1]) % N > 3:   # une picos 'empatados'
                picos.append(i)
    if len(picos) > 1 and (picos[0] - picos[-1]) % N <= 3:
        picos.pop()
    if len(picos) != 5:
        return False
    vaos = [(picos[(k + 1) % 5] - picos[k]) % N for k in range(5)]
    return all(10 <= v <= 18 for v in vaos)      # 72 graus +- 20 graus


def _tirar_estrelas(im):
    """Apaga as estrelas (separadas do corpo do escudo, na parte de cima).
    Retorna (imagem, quantidade removida). Só remove um bloco se ele passar
    em TODAS as checagens: formato de estrela de 5 pontas, pequeno em relação
    ao escudo e posicionado no topo. Coroas e demais adereços ficam."""
    from PIL import Image, ImageChops
    alfa = im.getchannel("A")
    if alfa.getextrema()[0] >= 250:      # sem transparência: não dá p/ separar
        return im, 0
    W0, H0 = im.size
    esc = _LADO_ANALISE / max(W0, H0)
    w, h = max(1, round(W0 * esc)), max(1, round(H0 * esc))
    peq = alfa.resize((w, h), Image.BICUBIC)
    dados = peq.tobytes()
    mascara = bytearray(1 if v > 20 else 0 for v in dados)
    blocos = _componentes(mascara, w, h)
    if len(blocos) < 2:
        return im, 0
    blocos.sort(key=len, reverse=True)
    principal = blocos[0]
    px0, py0, px1, py1, _, _ = _geometria(principal, w)
    ph = py1 - py0 + 1
    remover = []
    for pix in blocos[1:]:
        if len(pix) > 0.15 * len(principal):          # grande demais p/ estrela
            continue
        x0, y0, x1, y1, mx, my = _geometria(pix, w)
        if (y1 - y0 + 1) > 0.35 * ph:
            continue
        if my > py0 + 0.30 * ph:                       # só estrelas do topo
            continue
        if _eh_estrela(pix, w):
            remover.append(pix)
    if not remover:
        return im, 0
    return _apagar_blocos(im, remover, w, h), len(remover)


def _apagar_blocos(im, blocos, w, h):
    """Deixa transparentes os pixels dos blocos (coordenadas da análise w*h)."""
    from PIL import Image, ImageChops
    marca = bytearray(w * h)
    for pix in blocos:
        for i in pix:
            marca[i] = 255
    m = Image.frombytes("L", (w, h), bytes(marca))
    m = m.resize(im.size, Image.BILINEAR).point(lambda v: 255 if v > 0 else 0)
    novo = im.copy()
    novo.putalpha(ImageChops.multiply(im.getchannel("A"), ImageChops.invert(m)))
    return novo


# Times cujo escudo perde a COROA (id do Sofascore -> nome, só p/ referência).
# Só estes ids são mexidos; os demais escudos mantêm coroas e outros adereços.
REMOVER_COROA_TIMES = {1968: "Santos"}


def _tirar_coroa(im):
    """Apaga a coroa que flutua ACIMA do escudo (solta do corpo). Só remove
    blocos pequenos, totalmente acima do topo do escudo e centralizados nele.
    Retorna (imagem, quantidade de blocos removidos)."""
    from PIL import Image
    alfa = im.getchannel("A")
    if alfa.getextrema()[0] >= 250:
        return im, 0
    W0, H0 = im.size
    esc = _LADO_ANALISE / max(W0, H0)
    w, h = max(1, round(W0 * esc)), max(1, round(H0 * esc))
    dados = alfa.resize((w, h), Image.BICUBIC).tobytes()
    blocos = _componentes(bytearray(1 if v > 2 else 0 for v in dados), w, h)
    if len(blocos) < 2:
        return im, 0
    blocos.sort(key=len, reverse=True)
    principal = blocos[0]
    px0, py0, px1, py1, pmx, _ = _geometria(principal, w)
    pw, ph = px1 - px0 + 1, py1 - py0 + 1
    remover = []
    for pix in blocos[1:]:
        if len(pix) > 0.15 * len(principal):
            continue
        x0, y0, x1, y1, mx, my = _geometria(pix, w)
        if y1 > py0 + 0.04 * ph:                 # tem que estar acima do topo
            continue
        if (y1 - y0 + 1) > 0.30 * ph or (x1 - x0 + 1) > 0.60 * pw:
            continue
        if abs(mx - pmx) > 0.20 * pw:            # centralizada sobre o escudo
            continue
        remover.append(pix)
    if not remover:
        return im, 0
    return _apagar_blocos(im, remover, w, h), len(remover)


def _carregar_imagem(tipo, id_):
    from PIL import Image
    chave = (tipo, id_)
    if chave in _imagens_mem:
        return _imagens_mem[chave]
    imagem = None
    arq = baixar_imagem(tipo, id_)
    if arq:
        try:
            im = Image.open(arq).convert("RGBA")
            if tipo == "team" and REMOVER_ESTRELAS:
                im, n_est = _tirar_estrelas(im)
                if n_est:
                    print(f"  escudo {id_}: {n_est} estrela(s) removida(s) "
                          f"(só o que foi confirmado como estrela de 5 pontas)")
            if tipo == "team" and str(id_).isdigit() and \
                    int(id_) in REMOVER_COROA_TIMES:
                im, n_cor = _tirar_coroa(im)
                print(f"  escudo {id_} ({REMOVER_COROA_TIMES[int(id_)]}): "
                      + ("coroa removida" if n_cor else
                         "coroa NÃO encontrada (nada foi alterado)"))
            if tipo in ("team", "unique-tournament"):   # tira a margem transparente
                caixa = im.getchannel("A").point(
                    lambda v: 255 if v > 16 else 0).getbbox()
                im = im.crop(caixa) if caixa else im
            imagem = im
        except Exception:  # noqa
            imagem = None
    if imagem is not None:       # falhas não ficam guardadas: pode baixar depois
        _imagens_mem[chave] = imagem
        if tipo == "team":
            # Deslocamento vertical manual por ID. Valor positivo desce;
            # valor negativo sobe. A proporção é aplicada à altura renderizada.
            ajuste = _ajustes_verticais_escudos().get(str(id_), 0.0)
            _centro_escudo_cache[id(imagem)] = (imagem, ajuste)
    return imagem


def _carregar_escudo(team_id):
    return _carregar_imagem("team", team_id)


# True = escudos escuros ganham um disco claro atrás (ajuda a enxergar no
# fundo escuro). False = todos os escudos ficam sem fundo.
FUNDO_PARA_ESCUDOS_ESCUROS = False


def _escudo_escuro(pequeno):
    from PIL import ImageStat
    mascara = pequeno.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    if not mascara.getbbox():
        return False
    r, g, b = ImageStat.Stat(pequeno.convert("RGB"), mask=mascara).mean[:3]
    return _lum((r, g, b)) < 0.40


def _redimensionar_escudo(escudo, caixa):
    from PIL import Image
    w, h = escudo.size
    esc = min(caixa / w, caixa / h)
    return escudo.resize((max(1, round(w * esc)), max(1, round(h * esc))),
                         Image.LANCZOS)


_adorno_cache = {}
_centro_escudo_cache = {}  # (imagem, fração vertical manual; + desce / - sobe)


def _medir_adorno_perfil(escudo):
    """Fração (0 a 0,40) da altura do escudo ocupada por um adereço no TOPO
    (coroa, águia, galo...) que fica acima do corpo do escudo. 0 = não achou.
    Procura no perfil de larguras (linha a linha) um 'pescoço' (o perfil
    estreita depois do adereço) ou um degrau brusco (adereço bem mais estreito
    que o corpo). Escudos comuns, que só vão alargando de cima p/ baixo, dão 0."""
    from PIL import Image
    N = 100
    w0, h0 = escudo.size
    esc = N / max(w0, h0)
    w, h = max(1, round(w0 * esc)), max(1, round(h0 * esc))
    if h < 20 or w < 8:
        return 0.0
    alfa = escudo.getchannel("A").resize((w, h), Image.BILINEAR).point(
        lambda v: 255 if v > 90 else 0)
    larg = []
    for y in range(h):
        bb = alfa.crop((0, y, w, y + 1)).getbbox()
        larg.append(bb[2] - bb[0] if bb else 0)
    maxw = max(larg)
    if maxw < 10:
        return 0.0
    p = [v / maxw for v in larg]
    limite = int(0.42 * h)
    minimo_h = max(3, int(0.07 * h))
    topo_corpo = None

    # 1) 'pescoço': depois de um adereço de largura razoável o perfil afina
    mx = p[0]
    for y in range(1, limite):
        if mx >= 0.20 and p[y] <= 0.75 * mx:
            fim = None                   # linha em que o corpo volta a alargar
            for yy in range(y, min(h, y + int(0.45 * h))):
                if p[yy] >= 0.90 * mx and yy > y:
                    fim = yy
                    break
            if fim is not None:
                menor = min(p[y:fim + 1])
                ult = max(i for i in range(y, fim + 1) if p[i] <= menor + 0.02)
                if ult + 1 >= minimo_h:
                    topo_corpo = ult + 1
            break
        mx = max(mx, p[y])

    # 2) degrau: adereço estreito sobre um corpo de topo reto
    if topo_corpo is None:
        for y in range(max(2, int(0.06 * h)), limite):
            if p[y] - p[y - 1] >= 0.25 and p[y - 1] >= 0.15 \
                    and max(p[:y]) < 0.8 * max(p[y:y + 6]):
                topo_corpo = y
                break

    if topo_corpo is None or not minimo_h <= topo_corpo <= 0.40 * h:
        return 0.0
    return topo_corpo / h


# AJUSTE VERTICAL MANUAL DOS ESCUDOS ----------------------------------------
# Valor proporcional à altura renderizada do escudo:
#   positivo = desce | negativo = sobe | zero = posição original.
# Ex.: 0.05 desloca o escudo para baixo em 5% da sua altura.
# Cadastre o ID do Sofascore como texto. O mesmo ajuste vale para agenda,
# classificação e demais artes que utilizam as funções de colagem de escudos.
AJUSTE_VERTICAL_ESCUDOS = {
    "1957": 0.05,   # Corinthians: descer 5% da altura do escudo
    "3215": -0.09,  # Racing Club: subir 9% da altura do escudo
}
ARQ_AJUSTE_VERTICAL_ESCUDOS = PASTA_BASE / "ajuste_vertical_escudos.json"


def _ajustes_verticais_escudos():
    """Lê os ajustes padrão e permite sobrescrevê-los por arquivo JSON."""
    ajustes = dict(AJUSTE_VERTICAL_ESCUDOS)
    try:
        if ARQ_AJUSTE_VERTICAL_ESCUDOS.exists():
            dados = json.loads(
                ARQ_AJUSTE_VERTICAL_ESCUDOS.read_text(encoding="utf-8"))
            ajustes.update({str(k): float(v) for k, v in dados.items()})
    except Exception as exc:  # noqa
        print(f"Aviso: não foi possível ler ajustes verticais dos escudos: {exc}")
    # Limita o deslocamento a 45% da altura para evitar valores acidentais.
    return {str(k): max(-0.45, min(0.45, float(v)))
            for k, v in ajustes.items()}


def _ajustes_manuais():
    ajustes = {}
    try:
        if ARQ_AJUSTE_ESCUDOS.exists():
            for k, v in json.loads(
                    ARQ_AJUSTE_ESCUDOS.read_text(encoding="utf-8")).items():
                ajustes[str(k)] = float(v)
    except Exception:  # noqa
        pass
    for k, v in AJUSTE_ESCUDOS.items():
        ajustes[str(k)] = float(v)
    return {k: max(0.0, min(0.45, v)) for k, v in ajustes.items()}


def _medir_adorno_abertura(escudo, N=100):
    """Plano B para adereços SEM 'pescoço' (coroa encostada no corpo, como no
    Racing ou no Corinthians). Procura o ponto mais alto onde cabe um
    retângulo largo (55% da largura do escudo) totalmente dentro do desenho:
    coroas, águias e pontas são mais estreitas que o corpo e não comportam o
    retângulo; o corpo (bola, quadrado, triângulo) comporta. Só aceita o
    resultado quando ele é claramente um adereço (entre 11% e 40% da altura e
    tudo acima dele mais estreito que o corpo); senão devolve 0."""
    from PIL import Image
    w0, h0 = escudo.size
    esc = N / max(w0, h0)
    w, h = max(1, round(w0 * esc)), max(1, round(h0 * esc))
    if h < 20 or w < 8:
        return 0.0
    dados = escudo.getchannel("A").resize((w, h), Image.BILINEAR).point(
        lambda v: 255 if v > 90 else 0).tobytes()
    linhas = [[dados[y * w + x] > 0 for x in range(w)] for y in range(h)]
    ext = []
    for lin in linhas:
        xs = [x for x, v in enumerate(lin) if v]
        ext.append(xs[-1] - xs[0] + 1 if xs else 0)
    larg_max = max(ext)
    if larg_max < 10:
        return 0.0
    kx = max(3, round(0.55 * larg_max))       # largura do retângulo
    ky = max(2, round(0.10 * h))              # altura do retângulo
    cabe = [[False] * w for _ in range(h)]    # cabe[y][x]: linha de kx pixels
    for y, lin in enumerate(linhas):          # cheios começando em x
        seq = 0
        for x, v in enumerate(lin):
            seq = seq + 1 if v else 0
            if seq >= kx:
                cabe[y][x - kx + 1] = True
    topo = None
    for y0 in range(0, h - ky + 1):
        if any(all(cabe[y][x] for y in range(y0, y0 + ky))
               for x in range(w)):
            topo = y0
            break
    if topo is None:
        return 0.0
    frac = topo / h
    if not 0.11 <= frac <= 0.40:
        return 0.0
    # Não exija que o adereço seja muito estreito: águias e coroas largas
    # podem ocupar quase toda a largura do corpo. O limite anterior (75%)
    # descartava justamente esses casos e deixava o centro deslocado.
    if max(ext[:topo]) > 0.92 * larg_max:
        return 0.0
    return frac


def _medir_adorno(escudo):
    """Fração da altura ocupada pelo adereço do topo (0 = não tem). Tenta o
    método do contorno (com 'pescoço'); se não achar nada, tenta o da
    abertura (adereço encostado no corpo)."""
    frac = _medir_adorno_perfil(escudo)
    if frac <= 0:
        frac = _medir_adorno_abertura(escudo)
    return frac


def _adorno_do_escudo(escudo):
    chave = id(escudo)
    ja = _adorno_cache.get(chave)
    if ja is not None and ja[0] is escudo:
        return ja[1]
    try:
        frac = _medir_adorno(escudo)
    except Exception:  # noqa
        frac = 0.0
    _adorno_cache[chave] = (escudo, frac)
    return frac


def _escudo_no_tamanho(escudo, diam):
    """Redimensiona todos os escudos pela mesma caixa, sem inferir adornos.
    O alinhamento vertical é tratado separadamente por ajuste fixo de ID."""
    caixa = diam * 0.94
    pequeno = _redimensionar_escudo(escudo, caixa)
    if IGUALAR_AREA_ESCUDOS:
        area = sum(pequeno.getchannel("A").histogram()[129:])
        if area > 0:
            f = max(0.85, min(1.0, (0.52 * caixa * caixa / area) ** 0.25))
            if f < 0.995:
                pequeno = _redimensionar_escudo(escudo, caixa * f)
    return pequeno


def _deslocamento_vertical_escudo(escudo, pequeno):
    """Retorna o deslocamento manual em pixels na escala atual.

    Positivo = desce; negativo = sobe. O valor cadastrado é uma fração
    da altura renderizada, mantendo a correção proporcional em artes
    de tamanhos diferentes. Escudos sem ID cadastrado não são deslocados.
    """
    item = _centro_escudo_cache.get(id(escudo))
    proporcao = item[1] if item is not None and item[0] is escudo else 0.0
    return round(proporcao * pequeno.height)


def _colar_escudo(img, cx, cy, diam, escudo):
    """Cola o escudo real dentro de um quadrado diam x diam, sem distorcer.
    Escudos escuros ganham um disco claro atrás para não sumirem no fundo."""
    from PIL import Image, ImageDraw
    pequeno = _escudo_no_tamanho(escudo, diam)
    if FUNDO_PARA_ESCUDOS_ESCUROS and _escudo_escuro(pequeno):
        pequeno = _redimensionar_escudo(escudo, diam * 0.78)
        S = 4
        disco = Image.new("RGBA", (diam * S, diam * S), (0, 0, 0, 0))
        ImageDraw.Draw(disco).ellipse([0, 0, diam * S - 1, diam * S - 1],
                                      fill=(244, 246, 250, 238))
        disco = disco.resize((diam, diam), Image.LANCZOS)
        img.paste(disco, (int(cx - diam / 2), int(cy - diam / 2)), disco)
    pw, ph = pequeno.size
    deslocamento = _deslocamento_vertical_escudo(escudo, pequeno)
    img.paste(pequeno, (int(cx - pw / 2),
                        int(cy - ph / 2) + deslocamento), pequeno)


def _desenhar_botao(img, cx, cy, diam, nome):
    """Plano B: 'botão' redondo com as cores do clube (ou sigla em cinza)."""
    from PIL import Image, ImageDraw
    sigla, estilo, c1, c2, aro, conhecido = estilo_clube(nome)
    S = 4
    D = diam * S

    base = Image.new("RGBA", (D, D), c1 + (255,))
    bd = ImageDraw.Draw(base)
    if estilo == "stripes":
        n = 6
        w = D / n
        for i in range(1, n, 2):
            bd.rectangle([i * w, 0, (i + 1) * w, D], fill=c2 + (255,))
    elif estilo == "halves":
        bd.rectangle([D // 2, 0, D, D], fill=c2 + (255,))

    mascara = Image.new("L", (D, D), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, D - 1, D - 1], fill=255)
    botao = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    botao.paste(base, (0, 0), mascara)

    d = ImageDraw.Draw(botao)
    d.ellipse([0, 0, D - 1, D - 1], outline=aro + (255,), width=int(D * 0.075))
    ins = int(D * 0.13)
    d.ellipse([ins, ins, D - 1 - ins, D - 1 - ins], outline=aro + (255,),
              width=max(2, int(D * 0.018)))
    if not conhecido:
        d.text((D // 2, D // 2), sigla, font=_fonte(int(D * 0.34), True),
               fill=(255, 255, 255, 255), anchor="mm")

    pequeno = botao.resize((diam, diam), Image.LANCZOS)
    img.paste(pequeno, (int(cx - diam / 2), int(cy - diam / 2)), pequeno)


def desenhar_escudo(img, cx, cy, diam, nome, team_id=None):
    """Escudo real do Sofascore; se não houver, o 'botão' com as cores."""
    if team_id:
        escudo = _carregar_escudo(team_id)
        if escudo is not None:
            _colar_escudo(img, cx, cy, diam, escudo)
            return
    _desenhar_botao(img, cx, cy, diam, nome)


# --------------------------------------------------------------------------
# TEXTURA DO FUNDO  (logo da competição, bem suave)
# --------------------------------------------------------------------------
_logo_custom_cache = {}


def _caixa(img, caixa, cor, alfa=1.0, raio=0):
    """Retângulo (com cantos arredondados, se raio) translúcido: a textura do
    fundo continua aparecendo por baixo."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = (int(round(v)) for v in caixa)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w <= 0 or h <= 0:
        return
    S = 3 if raio else 1
    m = Image.new("L", (w * S, h * S), 0)
    dr = ImageDraw.Draw(m)
    v = max(0, min(255, int(255 * alfa)))
    if raio:
        dr.rounded_rectangle([0, 0, w * S - 1, h * S - 1], radius=raio * S,
                             fill=v)
        m = m.resize((w, h), Image.LANCZOS)
    else:
        dr.rectangle([0, 0, w - 1, h - 1], fill=v)
    img.paste(tuple(cor), (x0, y0), m)


def _logo_competicao():
    """Logo da competição: o enviado pelo painel (logos_competicao/custom_ID.png)
    ou, se não houver, o do Sofascore (baixado uma vez e guardado)."""
    from PIL import Image
    custom = PASTA_LOGOS_COMP / f"custom_{TOURNAMENT_ID}.png"
    if custom.exists():
        try:
            chave = (str(custom), custom.stat().st_mtime_ns)
            if chave not in _logo_custom_cache:
                im = Image.open(custom).convert("RGBA")
                caixa = im.getchannel("A").getbbox()
                _logo_custom_cache[chave] = im.crop(caixa) if caixa else im
            return _logo_custom_cache[chave]
        except Exception:  # noqa
            pass
    if not TOURNAMENT_ID:
        return None
    return _carregar_imagem("unique-tournament", TOURNAMENT_ID)


def _alfa_textura():
    try:
        v = float(CFG.get("textura_opacidade", 7))
    except (TypeError, ValueError):
        v = 7.0
    return max(0.0, min(0.40, v / 100))


def _logo_pronto(logo, caixa, alfa, angulo=0):
    """(fonte, máscara) do logo redimensionado para caber em 'caixa' px.
    'fonte' é uma cor (modo uma cor) ou a imagem (cores originais); a
    máscara já leva a opacidade 'alfa' (0-1)."""
    from PIL import Image, ImageChops
    pq = _redimensionar_escudo(logo, caixa)
    a = pq.getchannel("A")
    if a.getextrema()[0] >= 250:       # logo sem transparência: usa o contraste
        g = pq.convert("L")            # com a cor do canto como "fundo"
        a = ImageChops.difference(
            g, Image.new("L", g.size, g.getpixel((0, 0)))
        ).point(lambda v: min(255, v * 3))
    pal = _pal()
    if str(CFG.get("textura_cor") or "mono") == "original":
        fonte, mod = pq.convert("RGB"), a
    else:
        fonte = pal["marca"]
        lum = pq.convert("L")
        # partes escuras do logo (no tema claro) ou claras (no escuro) ficam
        # um pouco mais marcadas: mantém o desenho sem virar uma mancha
        detalhe = ImageChops.invert(lum) if pal["modo"] == "claro" else lum
        mod = ImageChops.multiply(
            a, detalhe.point(lambda v: 115 + v * 140 // 255))
    mascara = mod.point(lambda v: int(v * alfa))
    if angulo:
        mascara = mascara.rotate(angulo, resample=Image.BICUBIC, expand=True)
        if not isinstance(fonte, tuple):
            fonte = fonte.rotate(angulo, resample=Image.BICUBIC, expand=True)
    return fonte, mascara


ESTILOS_FUNDO = {
    "auto": "Automático (um desenho por competição)",
    "triangulos": "Triângulos",
    "chevron": "Zigue-zague",
    "listras": "Listras diagonais",
    "aneis": "Anéis concêntricos",
    "quadriculado": "Quadriculado",
    "estrelas": "Estrelas (estilo Champions)",
    "losangos": "Losangos",
    "hexagonos": "Favo de mel (hexágonos)",
    "bolinhas": "Bolinhas (pontilhado)",
    "ondas": "Ondas",
    "espanha": "Espanha (azulejo mourisco)",
    "alemanha": "Alemanha (faixas da bandeira)",
    "franca": "França (flor-de-lis)",
    "brasil": "Brasil (losango da bandeira)",
    "imagem": "Minha própria imagem (enviada por mim)",
    "logo": "Só o logo grande (marca d'água)",
    "logo_repetido": "Logo repetido",
    "nenhum": "Sem desenho",
}
# estilos sorteados quando o desenho é "auto" (NÃO acrescente nada aqui: muda o
# desenho das competições que já usam o automático)
ESTILOS_GERADOS = ("triangulos", "chevron", "listras", "aneis")
ESTILOS_NOVOS = ("quadriculado", "estrelas", "losangos", "hexagonos",
                 "bolinhas", "ondas",
                 "espanha", "alemanha", "franca", "brasil")
ESTILOS_DESENHADOS = ESTILOS_GERADOS + ESTILOS_NOVOS
# desenho de cada competição quando o estilo é "auto" (id no Sofascore)
ESTILO_AUTO = {23: "chevron", 8: "espanha", 679: "listras", 17: "triangulos",
               35: "alemanha", 34: "franca", 325: "brasil", 7: "logo"}


def _estilo_automatico():
    tid = int(TOURNAMENT_ID or 0)
    return ESTILO_AUTO.get(tid) or ESTILOS_GERADOS[tid % len(ESTILOS_GERADOS)]


def _estilo_fundo():
    e = str(CFG.get("estilo_fundo") or "").strip()
    if e not in ESTILOS_FUNDO:        # cadastros antigos (campo "textura")
        e = {"nenhuma": "nenhum", "marca": "logo"}.get(
            str(CFG.get("textura") or ""), "auto")
    if e == "auto":
        e = _estilo_automatico()
    return e


def _logo_grande_ativo():
    """True se um logo grande e suave já ocupa o fundo."""
    e = _estilo_fundo()
    return e == "logo" or (bool(CFG.get("logo_sobre_padrao"))
                           and (e in ESTILOS_DESENHADOS or e == "imagem"))


def _padrao_geometrico(img, estilo):
    """Desenho de fundo no estilo da marca (triângulos, zigue-zague, listras,
    anéis, quadriculado, estrelas, losangos, favo de mel, bolinhas e ondas),
    em tons da própria cor da competição e bem suave. É sempre o mesmo
    desenho para o mesmo tamanho de imagem. Todos seguem uma grade regular
    (nada de peças soltas ou giradas ao acaso)."""
    import math
    import random
    from PIL import Image, ImageChops, ImageDraw
    f = _alfa_textura()
    if f <= 0:
        return
    W, H = img.size
    S = 2                                   # desenha em dobro e reduz (bordas lisas)
    w, h = W * S, H * S
    rnd = random.Random(int(TOURNAMENT_ID or 0) * 7919 + W * 31 + H)
    masks = [Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)]  # claro, escuro
    draws = [ImageDraw.Draw(m) for m in masks]

    def val(idx, mult):
        return int(255 * min(0.55, f * mult))

    # no tema claro o traço "claro" (branco) quase some: lá usa-se o escuro
    claro_idx = 1 if _pal()["modo"] == "claro" else 0

    def tom():
        """(0 claro | 1 escuro, valor) com intensidade variada."""
        if rnd.random() < 0.5:
            return 0, val(0, rnd.choice((1.2, 1.8, 2.4)))
        return 1, val(1, rnd.choice((1.5, 2.2, 3.0)))

    if estilo == "triangulos":
        T = w * 0.095
        alt = T * math.sqrt(3) / 2
        for r in range(int(h / alt) + 3):
            y0 = r * alt
            off = T / 2 if r % 2 else 0
            for c in range(int(w / T) + 3):
                x0 = c * T - T + off
                cima = [(x0, y0 + alt), (x0 + T, y0 + alt), (x0 + T / 2, y0)]
                baixo = [(x0 + T / 2, y0), (x0 + 3 * T / 2, y0), (x0 + T, y0 + alt)]
                if rnd.random() < 0.07:        # losango = dois triângulos
                    i, v = tom()
                    draws[i].polygon(cima, fill=v)
                    draws[i].polygon(baixo, fill=v)
                else:
                    for tri in (cima, baixo):
                        if rnd.random() < 0.16:
                            i, v = tom()
                            draws[i].polygon(tri, fill=v)
        for _ in range(int(w / T * h / alt * 0.025)):    # triângulos pequenos
            s = T * rnd.uniform(0.22, 0.38)
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            a = s * math.sqrt(3) / 2
            tri = ([(x, y + a), (x + s, y + a), (x + s / 2, y)]
                   if rnd.random() < 0.5 else
                   [(x, y), (x + s, y), (x + s / 2, y + a)])
            i, v = tom()
            draws[i].polygon(tri, fill=v)

    elif estilo == "chevron":
        A = w * 0.06
        grosso, passo = A * 1.5, A * 3.2
        n = int(w / A) + 5
        yb, k = -2 * A, 0
        while yb < h + 2 * A:
            fase = (k % 2) * A
            topo = [(i * A - 2 * A - fase, yb + (A if i % 2 else 0))
                    for i in range(n)]
            baixo = [(x, y + grosso) for x, y in reversed(topo)]
            i = k % 2
            draws[i].polygon(topo + baixo, fill=val(i, 1.8 if i == 0 else 2.2))
            yb += passo
            k += 1

    elif estilo == "listras":
        # faixas diagonais (45°) num ritmo regular: larga, fina, larga...
        u = w * 0.020
        ritmo = [(2.4, 0), (1.3, None), (0.8, 1), (1.3, None)]
        ciclo = sum(larg for larg, _ in ritmo) * u
        c = -ciclo
        while c < w + h + ciclo:
            for larg, tx in ritmo:
                c1 = c + larg * u
                if tx is not None:
                    draws[tx].polygon(
                        [(c, 0), (c1, 0), (c1 - h, h), (c - h, h)],
                        fill=val(tx, 1.8 if tx == 0 else 2.2))
                c = c1

    elif estilo == "aneis":
        # anéis concêntricos, centro exato da imagem e espelhados (o que há
        # à esquerda do eixo vertical existe igual à direita). Os anéis
        # alternam entre 6 e 8 setores, sempre com um setor centrado no eixo.
        cx, cy = w / 2, h / 2
        n_aneis, miolo = 4, 1.4              # o 4º anel toca as laterais
        faixa = (min(w, h) / 2) / (n_aneis + miolo)
        corte = faixa * 0.16                 # largura do corte entre setores
        raio_max = math.hypot(w / 2, h / 2) + faixa
        r, k = faixa * miolo, 0
        while r < raio_max:
            r_in, r_out = r, r + faixa
            n_set = 6 if k % 2 == 0 else 8
            passo = 2 * math.pi / n_set
            giro = math.pi / 2 - passo / 2   # setor 0 centrado no eixo vertical
            for j in range(n_set):
                a0 = giro + j * passo + corte / (2 * r_out)
                a1 = giro + (j + 1) * passo - corte / (2 * r_out)
                passos = 28
                ext = [(cx + r_out * math.cos(a0 + (a1 - a0) * t / passos),
                        cy + r_out * math.sin(a0 + (a1 - a0) * t / passos))
                       for t in range(passos + 1)]
                inte = [(cx + r_in * math.cos(a1 - (a1 - a0) * t / passos),
                         cy + r_in * math.sin(a1 - (a1 - a0) * t / passos))
                        for t in range(passos + 1)]
                i = (k + min(j, n_set - j)) % 2   # mesma cor nos dois lados
                draws[i].polygon(ext + inte,
                                 fill=val(i, 1.8 if i == 0 else 2.2))
            r += faixa
            k += 1

    elif estilo == "quadriculado":
        # tabuleiro: casas claras e escuras alternadas, tudo na mesma grade
        C = w * 0.055
        for r in range(int(h / C) + 2):
            for c in range(int(w / C) + 2):
                i = (r + c) % 2
                draws[i].rectangle([c * C, r * C, (c + 1) * C, (r + 1) * C],
                                   fill=val(i, 1.5 if i == 0 else 1.7))

    elif estilo == "estrelas":
        # campo de estrelas de cinco pontas em grade escalonada (3 tamanhos)
        D = w * 0.080
        dy = D * 0.866

        def estrela(cx, cy, R):
            pts = []
            for k in range(10):
                a_ = -math.pi / 2 + k * math.pi / 5
                rr = R if k % 2 == 0 else R * 0.42
                pts.append((cx + rr * math.cos(a_), cy + rr * math.sin(a_)))
            return pts

        for r in range(int(h / dy) + 3):
            for c in range(int(w / D) + 3):
                cx = (c + (0.5 if r % 2 else 0)) * D - D
                cy = r * dy - dy
                t = (r + c) % 3
                if t == 0:
                    draws[claro_idx].polygon(
                        estrela(cx, cy, D * 0.34),
                        fill=val(claro_idx, 1.8 if claro_idx == 0 else 2.2))
                elif t == 1:
                    draws[1].polygon(estrela(cx, cy, D * 0.22),
                                     fill=val(1, 2.2))
                else:
                    draws[claro_idx].polygon(
                        estrela(cx, cy, D * 0.14),
                        fill=val(claro_idx, 1.4 if claro_idx == 0 else 1.8))

    elif estilo == "losangos":
        # arlequim: colunas de losangos que alternam claro e escuro
        Wd = w * 0.070
        Hd = Wd * 1.60
        enc = 0.90                              # deixa uma fresta entre eles
        for j in range(int(h / (Hd / 2)) + 3):
            for i in range(int(w / (Wd / 2)) + 3):
                if (i + j) % 2:
                    continue
                cx, cy = (i - 1) * Wd / 2, (j - 1) * Hd / 2
                t = i % 2
                forma = [(cx, cy - Hd / 2 * enc), (cx + Wd / 2 * enc, cy),
                         (cx, cy + Hd / 2 * enc), (cx - Wd / 2 * enc, cy)]
                draws[t].polygon(forma, fill=val(t, 1.7 if t == 0 else 2.0))

    elif estilo == "hexagonos":
        R = w * 0.046
        dx, dy = math.sqrt(3) * R, 1.5 * R
        for r in range(int(h / dy) + 3):
            for c in range(int(w / dx) + 3):
                cx = (c + (0.5 if r % 2 else 0)) * dx - dx
                cy = r * dy - dy
                q = c - (r - (r & 1)) // 2
                t = (q - r) % 3
                if t == 2:
                    continue
                forma = [(cx + R * 0.92 * math.cos(math.radians(30 + 60 * k)),
                          cy + R * 0.92 * math.sin(math.radians(30 + 60 * k)))
                         for k in range(6)]
                draws[t].polygon(forma, fill=val(t, 1.8 if t == 0 else 2.2))

    elif estilo == "bolinhas":
        # pontilhado em grade escalonada; as bolinhas crescem para o canto
        # inferior direito (efeito meio-tom)
        D = w * 0.034
        dy = D * 0.866
        i = claro_idx
        for r in range(int(h / dy) + 2):
            for c in range(int(w / D) + 2):
                cx = (c + (0.5 if r % 2 else 0)) * D
                cy = r * dy
                t = max(0.0, min(1.0, 0.55 * cx / w + 0.45 * cy / h))
                rad = D * (0.07 + 0.27 * t)
                draws[i].ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                                 fill=val(i, 2.0 if i == 0 else 2.4))

    elif estilo == "ondas":
        gap = w * 0.050
        amp, lam, grosso = gap * 0.42, w * 0.26, gap * 0.46
        n = int(w / 14) + 2
        xs = [i_ * (w / (n - 1)) for i_ in range(n)]
        yb, k = -gap, 0
        while yb < h + 2 * gap:
            topo = [(x, yb + amp * math.sin(2 * math.pi * x / lam)) for x in xs]
            baixo = [(x, y + grosso) for x, y in reversed(topo)]
            i = k % 2
            draws[i].polygon(topo + baixo,
                             fill=val(i, 1.8 if i == 0 else 2.2))
            yb += gap
            k += 1


    elif estilo == "espanha":
        # azulejo mourisco (Andaluzia): estrelas de 8 pontas numa grade
        # quadrada, com losangos nos vãos. Um azulejo fica no centro exato.
        P = w * 0.150
        R = P * 0.40
        r_int = R * 0.765                    # raio interno da estrela {8/2}

        def estrela8(cx_, cy_, rr, giro=0.0):
            pts = []
            for k_ in range(16):
                a_ = giro + k_ * math.pi / 8
                rad = rr if k_ % 2 == 0 else rr * 0.765
                pts.append((cx_ + rad * math.cos(a_), cy_ + rad * math.sin(a_)))
            return pts

        n_x, n_y = int(w / P / 2) + 3, int(h / P / 2) + 3
        for j in range(-n_y, n_y + 1):
            for i in range(-n_x, n_x + 1):
                x_, y_ = w / 2 + i * P, h / 2 + j * P
                draws[claro_idx].polygon(
                    estrela8(x_, y_, R, math.pi / 8 * 0),
                    fill=val(claro_idx, 1.8 if claro_idx == 0 else 2.2))
                draws[1].polygon(estrela8(x_, y_, R * 0.46, math.pi / 8),
                                 fill=val(1, 2.2))
                q = P * 0.17                  # losango no vão entre 4 estrelas
                xv, yv = x_ + P / 2, y_ + P / 2
                draws[1].polygon([(xv, yv - q), (xv + q, yv),
                                  (xv, yv + q), (xv - q, yv)],
                                 fill=val(1, 2.0))

    elif estilo == "alemanha":
        # faixas horizontais em trio (preto-vermelho-dourado da bandeira),
        # em três intensidades; o trio do meio fica no centro da imagem.
        b = h * 0.036                         # altura de cada faixa
        passo = b * 3.9                       # trio + respiro
        n = int(h / passo / 2) + 3
        for j in range(-n, n + 1):
            y0 = h / 2 - 1.5 * b + j * passo
            draws[1].rectangle([0, y0, w, y0 + b], fill=val(1, 3.0))
            draws[0].rectangle([0, y0 + b, w, y0 + 2 * b],
                               fill=val(0, 1.1))
            draws[0].rectangle([0, y0 + 2 * b, w, y0 + 3 * b],
                               fill=val(0, 2.6))

    elif estilo == "franca":
        # flor-de-lis em grade "meio-passo", um brasão no centro exato
        def petala(p0, p1, p2, larg, n_=26):
            esq, dire = [], []
            for t_ in range(n_ + 1):
                t = t_ / n_
                x_ = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
                y_ = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
                dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
                dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
                nn = math.hypot(dx, dy) or 1
                hw = larg * math.sin(math.pi * t) ** 0.85
                esq.append((x_ - dy / nn * hw, y_ + dx / nn * hw))
                dire.append((x_ + dy / nn * hw, y_ - dx / nn * hw))
            return esq + dire[::-1]

        Px = w * 0.17
        Py = Px * 1.30
        Hf = Py * 0.80                        # altura da flor-de-lis

        def flor(cx_, cy_, i_cor):
            u = Hf
            def T(pt):                        # coordenadas da flor -> imagem
                return (cx_ + pt[0] * u, cy_ + pt[1] * u)
            partes = [
                petala((0, 0.08), (0.0, -0.22), (0, -0.52), 0.125),
                petala((0.04, -0.04), (0.46, -0.20), (0.36, 0.17), 0.105),
                petala((-0.04, -0.04), (-0.46, -0.20), (-0.36, 0.17), 0.105),
                petala((0, 0.22), (0.0, 0.36), (0, 0.50), 0.080),
            ]
            for pol in partes:
                draws[i_cor].polygon([T(q) for q in pol],
                                     fill=val(i_cor, 1.8 if i_cor == 0 else 2.2))
            draws[i_cor].rectangle(
                [cx_ - 0.24 * u, cy_ + 0.12 * u, cx_ + 0.24 * u, cy_ + 0.20 * u],
                fill=val(i_cor, 1.8 if i_cor == 0 else 2.2))

        n_x, n_y = int(w / Px / 2) + 3, int(h / Py / 2) + 3
        for j in range(-n_y, n_y + 1):
            for i in range(-n_x, n_x + 1):
                x_ = w / 2 + i * Px + (Px / 2 if j % 2 else 0)
                y_ = h / 2 + j * Py
                flor(x_, y_, claro_idx)
                q = Px * 0.055                # losango entre as flores
                xv, yv = x_ + Px / 2, y_ + Py / 2
                draws[1].polygon([(xv, yv - q * 1.5), (xv + q, yv),
                                  (xv, yv + q * 1.5), (xv - q, yv)],
                                 fill=val(1, 2.2))

    elif estilo == "brasil":
        # losango da bandeira com o círculo e a faixa curva, em grade
        # "meio-passo"; um losango fica no centro exato da imagem.
        Px = w * 0.27
        a_ = Px * 0.46                        # meia-largura do losango
        b_ = a_ * 0.70                        # meia-altura
        Py = b_ * 2.35
        rc = b_ * 0.58                        # raio do círculo

        def losango(cx_, cy_, ka, kb):
            return [(cx_, cy_ - kb), (cx_ + ka, cy_),
                    (cx_, cy_ + kb), (cx_ - ka, cy_)]

        n_x, n_y = int(w / Px / 2) + 3, int(h / Py / 2) + 3
        for j in range(-n_y, n_y + 1):
            for i in range(-n_x, n_x + 1):
                x_ = w / 2 + i * Px + (Px / 2 if j % 2 else 0)
                y_ = h / 2 + j * Py
                # contorno do losango (anel claro) e miolo mais escuro
                draws[claro_idx].polygon(losango(x_, y_, a_, b_),
                                         fill=val(claro_idx, 1.6 if claro_idx == 0 else 2.0))
                draws[claro_idx].polygon(losango(x_, y_, a_ * 0.88, b_ * 0.88),
                                         fill=0)
                draws[1].polygon(losango(x_, y_, a_ * 0.88, b_ * 0.88),
                                 fill=val(1, 1.5))
                # círculo (claro) com a faixa curva recortada
                draws[1].ellipse([x_ - rc, y_ - rc, x_ + rc, y_ + rc], fill=0)
                draws[claro_idx].ellipse([x_ - rc, y_ - rc, x_ + rc, y_ + rc],
                                         fill=val(claro_idx, 2.0 if claro_idx == 0 else 2.4))
                d_ = rc * 1.15
                Rb = d_ + rc * 0.06
                esp = rc * 0.20
                ext, inte = [], []
                for t_ in range(-30, 31):
                    f_ = t_ / 30 * 0.62
                    for rr, lst in ((Rb + esp / 2, ext), (Rb - esp / 2, inte)):
                        px_, py_ = x_ + rr * math.sin(f_), y_ + d_ - rr * math.cos(f_)
                        if math.hypot(px_ - x_, py_ - y_) <= rc * 0.995:
                            lst.append((px_, py_))
                if len(ext) > 2 and len(inte) > 2:
                    draws[claro_idx].polygon(ext + inte[::-1], fill=0)

    pal = _pal()
    for m, cor in zip(masks, (pal["pad_a"], pal["pad_b"])):
        img.paste(cor, (0, 0), m.resize((W, H), Image.LANCZOS))


# --------------------------------------------------------------------------
# FUNDO COM IMAGEM PRÓPRIA
# --------------------------------------------------------------------------
PASTA_FUNDOS = PASTA_BASE / "fundos_competicao"
_fundo_img_cache = {}


def caminho_fundo_personalizado(tid=None):
    """Arquivo da imagem de fundo enviada para a competição (ou None)."""
    tid = TOURNAMENT_ID if tid is None else tid
    arq = PASTA_FUNDOS / f"custom_{int(tid or 0)}.jpg"
    return arq if arq.exists() else None


def salvar_fundo_personalizado(tid, dados):
    """Guarda a imagem enviada (JPG/PNG/WEBP...), já em RGB e com no máximo
    2400 px. Levanta erro se o arquivo não for uma imagem."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(dados))
    im.load()
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):          # transparência vira branco
        im = im.convert("RGBA")
        base = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(base, im)
    im = im.convert("RGB")
    im.thumbnail((2400, 2400), Image.LANCZOS)
    PASTA_FUNDOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_FUNDOS / f"custom_{int(tid)}.jpg"
    im.save(destino, quality=92)
    _fundo_img_cache.clear()
    return destino


def remover_fundo_personalizado(tid):
    arq = PASTA_FUNDOS / f"custom_{int(tid)}.jpg"
    if arq.exists():
        arq.unlink()
    _fundo_img_cache.clear()


def _intensidade_fundo_imagem():
    try:
        v = float(CFG.get("fundo_imagem_intensidade", 28))
    except (TypeError, ValueError):
        v = 28.0
    return max(5.0, min(70.0, v)) / 100


def _mascaras_fundo_imagem(caminho, W, H):
    """Transforma uma foto qualquer num fundo minimalista: recorta para o
    formato da imagem, tira as cores, apaga os detalhes finos (desfoque),
    reequilibra o contraste e separa em duas máscaras (partes mais claras e
    mais escuras que a média). Pintadas com o claro/escuro da paleta, elas
    deixam só a 'sombra' da imagem, no tom da competição e sem mexer no
    brilho médio do fundo (o texto continua legível)."""
    from PIL import Image, ImageFilter, ImageOps, ImageStat
    alfa = _intensidade_fundo_imagem()
    chave = (str(caminho), caminho.stat().st_mtime_ns, W, H, round(alfa, 3))
    if chave in _fundo_img_cache:
        return _fundo_img_cache[chave]
    im = Image.open(caminho)
    im = ImageOps.exif_transpose(im).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.LANCZOS, centering=(0.5, 0.5))
    g = ImageOps.grayscale(im)
    g = g.filter(ImageFilter.GaussianBlur(max(3.0, W * 0.005)))
    g = ImageOps.autocontrast(g, cutoff=1)      # foto lavada/escura: corrige
    media = ImageStat.Stat(g).mean[0]
    media = max(30.0, min(225.0, media))
    lut_claro, lut_escuro = [], []
    for v in range(256):
        c = max(0.0, min(1.0, (v - media) / (255 - media))) ** 0.9
        e = max(0.0, min(1.0, (media - v) / media)) ** 0.9
        lut_claro.append(int(255 * min(0.75, c * alfa * 0.85)))
        lut_escuro.append(int(255 * min(0.75, e * alfa)))
    res = (g.point(lut_claro), g.point(lut_escuro))
    _fundo_img_cache[chave] = res
    return res


def _fundo_imagem(img):
    """Aplica a imagem própria como fundo. False se não houver imagem."""
    caminho = caminho_fundo_personalizado()
    if caminho is None:
        return False
    W, H = img.size
    claro, escuro = _mascaras_fundo_imagem(caminho, W, H)
    pal = _pal()
    img.paste(pal["pad_a"], (0, 0), claro)
    img.paste(pal["pad_b"], (0, 0), escuro)
    return True


def previa_fundo_personalizado(largura=960, altura=540):
    """Miniatura de como a imagem própria fica no fundo (para o painel)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (largura, altura), _pal()["bg"])
    if not _fundo_imagem(img):
        return None
    d = ImageDraw.Draw(img)
    _faixa_topo(d, largura)
    d.text((36, 40), "Agenda da rodada", font=_fonte(22),
           fill=_pal()["suave"])
    d.text((36, 76), str(CFG.get("nome") or "Competição"),
           font=_fonte_ajustada(d, str(CFG.get("nome") or "Competição"),
                                largura - 72, 40),
           fill=_pal()["txt"])
    _caixa(img, [28, 150, largura - 28, 202], _pal()["cartao"], 0.92, raio=8)
    d.text((48, 176), "Quarta, 4 Novembro 2026", font=_fonte(24, True),
           fill=_pal()["txt"], anchor="lm")
    for k, (h_, t_) in enumerate((("19h30", "Time A  x  Time B"),
                                  ("21h30", "Time C  x  Time D"))):
        cy = 250 + k * 80
        if k % 2:
            _caixa(img, [28, cy - 38, largura - 28, cy + 38],
                   _pal()["zebra_jogo"], 0.75)
        d.text((48, cy), h_, font=_fonte(30, True), fill=_pal()["ouro"],
               anchor="lm")
        d.text((200, cy), t_, font=_fonte(28, True), fill=_pal()["txt"],
               anchor="lm")
    return img


def _logo_grande(img, fator=0.8):
    """Um logo grande e suave, centralizado."""
    logo = _logo_competicao()
    if logo is None:
        return
    W, H = img.size
    fonte, m = _logo_pronto(logo, int(min(W, H) * fator),
                            min(_alfa_textura() * 1.4, 0.5))
    img.paste(fonte, ((W - m.width) // 2, (H - m.height) // 2), m)


def _logo_repetido(img, excluir_y=None):
    """Logo (grande) repetido em diagonal."""
    logo = _logo_competicao()
    if logo is None:
        return
    W, H = img.size
    lado = max(120, int(W * 0.17))
    fonte, m = _logo_pronto(logo, lado, _alfa_textura(), angulo=15)
    px, py = int(lado * 2.1), int(lado * 1.5)
    for fila, y in enumerate(range(-py // 2, H + py, py)):
        if excluir_y and y + m.height > excluir_y[0] and y < excluir_y[1]:
            continue
        desloc = px // 2 if fila % 2 else 0
        for x in range(-px + desloc, W + px, px):
            img.paste(fonte, (x, y), m)


def _textura_fundo(img, excluir_y=None):
    """Fundo da imagem, no estilo escolhido no cadastro da competição.
    excluir_y = (y0, y1): faixa que fica livre do logo repetido."""
    estilo = _estilo_fundo()
    if estilo == "nenhum":
        return
    try:
        if estilo == "imagem":
            if _fundo_imagem(img):
                if CFG.get("logo_sobre_padrao"):
                    _logo_grande(img, 0.55)
                return
            print("  aviso: a competição usa 'Minha própria imagem', mas não "
                  "há imagem enviada; usando o desenho automático.")
            estilo = _estilo_automatico()
        if _alfa_textura() <= 0:
            return
        if estilo in ESTILOS_DESENHADOS:
            _padrao_geometrico(img, estilo)
            if CFG.get("logo_sobre_padrao"):
                _logo_grande(img, 0.55)
        elif estilo == "logo":
            _logo_grande(img, 0.8)
        elif estilo == "logo_repetido":
            _logo_repetido(img, excluir_y)
    except Exception as exc:  # noqa
        print(f"  aviso: o fundo desenhado não foi gerado ({exc})")


def _preencher_vazio(img, y0, y1):
    """Logo (ou o nome) da competição, centralizado e suave, no espaço vazio
    entre y0 e y1 — usado quando as partes da agenda ficam com o mesmo tamanho."""
    from PIL import Image, ImageDraw
    W = img.size[0]
    livre = y1 - y0
    if livre < 60:
        return
    alfa = min(0.30, max(_alfa_textura(), 0.04) * 2.2)
    try:
        logo = _logo_competicao()
    except Exception:  # noqa
        logo = None
    cy = (y0 + y1) // 2
    if logo is not None:
        lado = int(min(livre * 0.70, W * 0.26))
        fonte, m = _logo_pronto(logo, lado, alfa)
        img.paste(fonte, ((W - m.width) // 2, cy - m.height // 2), m)
    else:                                   # sem logo: o nome da competição
        m = Image.new("L", (W, livre), 0)
        dm = ImageDraw.Draw(m)
        nome = str(CFG.get("nome_curto") or CFG.get("nome") or "")
        dm.text((W // 2, livre // 2), nome,
                font=_fonte_ajustada(dm, nome, int(W * 0.7),
                                     min(120, int(livre * 0.45))),
                fill=int(255 * alfa), anchor="mm")
        img.paste(_pal()["marca"], (0, y0), m)


# --------------------------------------------------------------------------
# ZONAS E CLASSIFICAÇÃO
# --------------------------------------------------------------------------
PALETA_EXTRA = [(150, 90, 220), (20, 170, 190), (230, 200, 40), (160, 160, 170)]
_ROTULOS_AUTO = {"libertadores": "Libertadores", "sudamericana": "Sul-Americana",
                 "sul-americana": "Sul-Americana", "sul americana": "Sul-Americana"}


def _categoria(texto):
    t = (texto or "").strip()
    tl = t.lower()
    if not tl:
        return None
    if "conf" in tl:
        return "ecl"
    if any(k in tl for k in ("europa", "sudamericana", "sul-americana",
                             "sul americana")):
        return "el"
    if any(k in tl for k in ("champions", "libertadores", "campe")):
        return "cl"
    if any(k in tl for k in ("releg", "rebaix", "descenso", "abstieg")):
        return "rel"
    return "x:" + t     # outra faixa (promoção, playoffs...): usa o próprio texto


def zonas_da_tabela(linhas):
    """posição -> faixa, lida do Sofascore (com plano B vindo do cadastro).
    Retorna (zonas, meta) onde meta[faixa] = (cor, rótulo)."""
    rotulos_cfg = {z["chave"]: z.get("rotulo") for z in CFG.get("zonas", [])}
    zonas, achou, extras, rot_auto = {}, set(), [], {}
    for r in linhas:
        texto = (r.get("promotion") or {}).get("text")
        cat = _categoria(texto)
        if not cat:
            continue
        zonas[r["position"]] = cat
        achou.add(cat)
        if cat.startswith("x:") and cat not in extras:
            extras.append(cat)
        for k, v in _ROTULOS_AUTO.items():
            if k in (texto or "").lower():
                rot_auto.setdefault(cat, v)

    padrao = [z for z in CFG.get("zonas", []) if z.get("ini")]
    if not achou:
        if padrao:
            print("  aviso: Sofascore não informou zonas; usando as posições "
                  "cadastradas.")
        usar = padrao
    else:
        usar = [z for z in padrao if z["chave"] == "rel" and "rel" not in achou]
    for z in usar:
        for pos in range(int(z["ini"]), int(z.get("fim") or z["ini"]) + 1):
            zonas.setdefault(pos, z["chave"])

    meta = {c: (cor, rotulos_cfg.get(c) or rot_auto.get(c) or rot)
            for c, (cor, rot) in CATEGORIAS.items()}
    manual = CFG.get("rotulos_faixas") or {}
    nomes_extra = {x: manual.get(x[2:]) or traduzir_fase(x[2:]) for x in extras}
    for x in extras:     # dois textos diferentes com o mesmo nome: mostra o original
        if list(nomes_extra.values()).count(nomes_extra[x]) > 1 \
                and not manual.get(x[2:]):
            nomes_extra[x] = x[2:]
    for i, x in enumerate(extras):
        meta[x] = (PALETA_EXTRA[i % len(PALETA_EXTRA)], nomes_extra[x])
        print(f"  faixa do Sofascore: '{x[2:]}' -> '{nomes_extra[x]}'")

    resumo = {}
    for pos, cat in sorted(zonas.items()):
        resumo.setdefault(cat, []).append(pos)
    print("  zonas:", {meta[c][1]: f"{v[0]}-{v[-1]}" for c, v in resumo.items()})
    return zonas, meta


# Colunas da imagem de classificação, em ordem. Opções: J (jogos), V (vitórias),
# E (empates), D (derrotas), GP (gols pró), GC (gols contra), SG (saldo de
# gols) e PTS (pontos, sempre aparece). Menos colunas = números maiores.
CLASSIF_COLUNAS = ["J", "V", "D", "GP", "SG", "PTS"]


def _posicoes_colunas(colunas, x_pts):
    """Borda direita de cada coluna: espaçadas por igual até a de pontos."""
    cols = [c for c in colunas if c != "PTS"] + ["PTS"]
    x0 = 560 if len(cols) <= 6 else 500
    passo = (x_pts - x0) / max(len(cols) - 1, 1)
    return {c: round(x0 + i * passo) for i, c in enumerate(cols)}


def gerar_classificacao(standings, caminho, subtitulo, linhas=None,
                        zonas=None, meta=None):
    """Tabela de classificação. Para tabelas grandes, quem chama passa só um
    pedaço das linhas (com as zonas já calculadas para a tabela inteira)."""
    from PIL import Image, ImageDraw
    todas = sorted(standings["standings"][0]["rows"],
                   key=lambda r: r["position"])
    if zonas is None:
        zonas, meta = zonas_da_tabela(todas)
    if linhas is None:
        linhas = todas

    # altura fixa 1440; a altura de cada linha se ajusta ao nº de times
    # (sem rodapé, sobra mais espaço: linhas, fontes e escudos maiores)
    n = max(len(linhas), 1)
    W, TOPO, MARGEM, H = 1080, 196, 50, 1440     # TOPO: respiro sob o subtítulo
    LH = max(30, min(66, (H - TOPO - 100) // n))
    k = min(1.0, LH / 58)

    def fs(base):
        return max(16, round(base * k))

    img = Image.new("RGB", (W, H), _pal()["bg"])

    _textura_fundo(img)
    d = ImageDraw.Draw(img)

    _faixa_topo(d, W)
    xt, xs = _logo_cabecalho(img, MARGEM + 20, 40, 40, 96, 144,
                             "classificacao")
    d.text((xt, 40), "Classificação", font=_fonte(56, True),
           fill=_pal()["txt"])
    d.text((xs, 112), subtitulo, font=_fonte(28),
           fill=_pal()["suave"])

    X_BARRA = MARGEM - 34          # barras das zonas: todas no mesmo x
    X_FAIXA = MARGEM - 14
    X_POS, X_ESCUDO, X_NOME = MARGEM + 46, MARGEM + 96, MARGEM + 141
    # borda direita de cada coluna (mesmo espaçamento entre todas).
    # Colunas mostradas: edite CLASSIF_COLUNAS (ex.: acrescente "E" e "GC").
    COL = _posicoes_colunas(CLASSIF_COLUNAS, W - MARGEM - 8)

    f_cab = _fonte(fs(23), True)
    for nome, x in COL.items():
        d.text((x, TOPO - 12), nome, font=f_cab, fill=_pal()["cab"],
               anchor="rs")

    f_nome, f_num, f_pts = _fonte(fs(32), True), _fonte(fs(31)), _fonte(fs(34), True)
    diam = min(48, LH - 10)
    larg_nome = min(COL.values()) - 45 - (X_NOME + 10)   # não invade a 1ª coluna
    for i, r in enumerate(linhas):
        pos = r["position"]
        y = TOPO + i * LH
        if pos % 2 == 0:
            _caixa(img, [X_FAIXA, y, W - MARGEM + 14, y + LH - 4],
                   _pal()["linha_alt"], 0.70)
        cy = y + (LH - 4) // 2
        yb = cy + round(11 * k)            # linha de base comum a toda a linha

        d.text((X_POS, yb), str(pos), font=f_nome, fill=_pal()["suave"],
               anchor="rs")
        desenhar_escudo(img, X_ESCUDO + 5, cy, diam, r["team"]["name"],
                        r["team"].get("id"))
        nome_exib = nome_time(r["team"]["name"])
        d.text((X_NOME + 10, yb), nome_exib,
               font=_fonte_ajustada(d, nome_exib, larg_nome, fs(32), minimo=16),
               fill=_pal()["txt"], anchor="ls")

        gp, gc = r.get("scoresFor", 0), r.get("scoresAgainst", 0)
        valores = {"J": r.get("matches", 0), "V": r.get("wins", 0),
                   "E": r.get("draws", 0), "D": r.get("losses", 0),
                   "GP": gp, "GC": gc, "SG": f"{gp - gc:+d}"}
        for kk, v in valores.items():
            if kk not in COL:
                continue
            d.text((COL[kk], yb), str(v), font=f_num, fill=_pal()["txt2"],
                   anchor="rs")
        d.text((COL["PTS"], yb), str(r.get("points", 0)), font=f_pts,
               fill=_pal()["txt"], anchor="rs")

    # barras das zonas: uma barra contínua por faixa, todas no mesmo x
    i = 0
    while i < len(linhas):
        cat = zonas.get(linhas[i]["position"])
        j = i
        while j + 1 < len(linhas) and zonas.get(linhas[j + 1]["position"]) == cat:
            j += 1
        if cat is not None:
            d.rounded_rectangle([X_BARRA, TOPO + i * LH, X_BARRA + 9,
                                 TOPO + (j + 1) * LH - 4],
                                radius=4, fill=meta[cat][0])
        i = j + 1

    # legenda (só as faixas que aparecem nesta imagem)
    presentes = {zonas.get(r["position"]) for r in linhas}
    usadas = [c for c in meta if c in presentes]
    tam_leg = 24                      # reduz até a legenda caber na largura
    while True:
        f_leg = _fonte(tam_leg)
        larguras = [36 + int(d.textlength(meta[c][1], font=f_leg))
                    for c in usadas]
        total = sum(larguras) + 34 * max(len(usadas) - 1, 0)
        if total <= W - 2 * 30 or tam_leg <= 16:
            break
        tam_leg -= 1
    x = max((W - total) // 2, MARGEM)
    y = TOPO + LH * len(linhas) + 22
    for c, w in zip(usadas, larguras):
        d.rounded_rectangle([x, y, x + 24, y + 24], radius=5, fill=meta[c][0])
        d.text((x + 36, y + 12), meta[c][1], font=f_leg,
               fill=_pal()["txt2"], anchor="lm")
        x += w + 34
    img.save(caminho)


def _fonte_ajustada(d, texto, largura_max, tam_max, negrito=True, minimo=20):
    tam = tam_max
    while tam > minimo:
        f = _fonte(tam, negrito)
        if d.textlength(texto, font=f) <= largura_max:
            return f
        tam -= 2
    return _fonte(minimo, negrito)


def _quebrar(d, texto, fonte, largura):
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if not atual or d.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    return linhas


def _texto_coluna(d, texto, x, cy, largura, cor, tam=26, negrito=False):
    """Escreve o texto numa coluna, em até 2 linhas, reduzindo se precisar."""
    while True:
        f = _fonte(tam, negrito)
        linhas = _quebrar(d, texto, f, largura)
        cabe = len(linhas) <= 2 and all(
            d.textlength(l, font=f) <= largura for l in linhas)
        if cabe or tam <= 18:
            break
        tam -= 2
    alt = tam + 8
    y0 = cy - (len(linhas) - 1) * alt / 2
    for i, linha in enumerate(linhas):
        d.text((x, y0 + i * alt), linha, font=f, fill=cor, anchor="lm")


# --------------------------------------------------------------------------
# LOGOS DAS EMISSORAS (coluna Transmissão da imagem da agenda)
# --------------------------------------------------------------------------
PASTA_LOGOS = PASTA_BASE / "logos"
ALT_SELO = 50
ESPACO_SELOS = 10

# canal -> (texto, cor do fundo, cor do texto). São selos desenhados pelo
# programa (cores aproximadas, não os logotipos oficiais). Para usar o logo
# oficial, salve um PNG na pasta "logos" com o nome da chave (ex.: disney.png,
# espn4.png, cazetv.png) e ele passa na frente do selo desenhado.
# canal -> (texto, cor do fundo, cor do texto)
# A chave é o nome do canal só com letras e números (ex.: "SporTV 2" -> "sportv2").
# ESPN (2, 3, 4 e no YouTube) tem selo próprio no código e não precisa estar aqui.
CANAIS_VISUAL = {
    # Globo
    "globo": ("Globo", (0, 140, 224), (255, 255, 255)),
    "sportv": ("SporTV", (26, 20, 110), (255, 255, 255)),
    "sportv2": ("SporTV 2", (26, 20, 110), (255, 255, 255)),
    "sportv3": ("SporTV 3", (26, 20, 110), (255, 255, 255)),
    "premiere": ("Premiere", (0, 150, 70), (255, 255, 255)),
    "globoplay": ("Globoplay", (240, 40, 80), (255, 255, 255)),
    # TV aberta e canais esportivos
    "record": ("Record", (10, 60, 150), (255, 255, 255)),
    "sbt": ("SBT", (52, 38, 168), (255, 255, 255)),
    "band": ("Band", (255, 204, 0), (0, 110, 50)),
    "bandsports": ("BandSports", (218, 24, 32), (255, 255, 255)),
    "nsports": ("N Sports", (0, 90, 50), (255, 255, 255)),
    "cazetv": ("Cazé TV", (20, 20, 20), (255, 255, 255)),
    "goat": ("GOAT", (20, 20, 20), (255, 255, 255)),
    "sportynet": ("SportyNet", (240, 52, 76), (255, 255, 255)),
    "dazn": ("DAZN", (240, 240, 0), (10, 10, 10)),
    "tnt": ("TNT", (0, 0, 0), (255, 255, 255)),
    "space": ("Space", (255, 205, 0), (20, 20, 20)),
    "tntsports": ("TNT Sports", (236, 0, 176), (255, 255, 255)),
    "bein": ("beIN Sports", (88, 44, 131), (255, 255, 255)),
    "skysports": ("Sky Sports", (0, 72, 168), (255, 255, 255)),
    "foxsports": ("Fox Sports", (0, 48, 135), (255, 255, 255)),
    "dsports": ("DSports", (0, 156, 222), (255, 255, 255)),
    "youtube": ("YouTube", (255, 0, 0), (255, 255, 255)),
    # Streaming
    "disney": ("Disney+", (17, 60, 207), (255, 255, 255)),
    "disneyplus": ("Disney+", (17, 60, 207), (255, 255, 255)),
    "star": ("Star+", (18, 18, 18), (255, 255, 255)),
    "max": ("HBO Max", (15, 15, 15), (255, 255, 255)),
    "hbomax": ("HBO Max", (15, 15, 15), (255, 255, 255)),
    "primevideo": ("Prime Video", (0, 168, 225), (255, 255, 255)),
    "amazonprimevideo": ("Prime Video", (0, 168, 225), (255, 255, 255)),
    "paramount": ("Paramount+", (0, 100, 255), (255, 255, 255)),
    "paramountplus": ("Paramount+", (0, 100, 255), (255, 255, 255)),
    "appletv": ("Apple TV", (0, 0, 0), (255, 255, 255)),
}
_PALETA_GENERICA = [(70, 90, 140), (110, 70, 140), (40, 120, 120),
                    (140, 90, 50), (90, 110, 60), (130, 60, 80)]
_cache_selos = {}


def _chave_canal(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _cores_contorno(fundo):
    """(externo, interno): contorno duplo do selo, em dois tons da própria cor.
    O externo é o mais chamativo (tom mais claro; mais escuro nas cores muito
    claras) e o interno é um tom escuro intermediário até o fundo do selo."""
    lum = 0.299 * fundo[0] + 0.587 * fundo[1] + 0.114 * fundo[2]
    if lum < 60:                       # preto / quase preto
        return (112, 118, 130), (58, 62, 72)
    if lum >= 190:                     # amarelos e claros
        return (tuple(int(c * 0.66) for c in fundo),
                tuple(int(c * 0.86) for c in fundo))
    return (tuple(int(c + (255 - c) * 0.45) for c in fundo),
            tuple(int(c * 0.62) for c in fundo))


def _selo_texto(texto, fundo, cor_texto, chip=None, youtube=False):
    """Selo arredondado com o nome do canal e, opcional, um círculo à direita
    com o número do canal ou com o ícone do YouTube."""
    from PIL import Image, ImageDraw
    S = 3
    H = ALT_SELO * S
    fonte = _fonte(int(H * 0.46), True)
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    larg_txt = int(medidor.textlength(texto, font=fonte))
    pad = int(H * 0.34)
    extra = bool(chip or youtube)
    larg = larg_txt + 2 * pad + (int(H * 0.72) + int(H * 0.12) if extra else 0)
    im = Image.new("RGBA", (larg, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ext, interno = _cores_contorno(fundo)
    raio, f = int(H * 0.22), max(2, int(H * 0.04))
    d.rounded_rectangle([0, 0, larg - 1, H - 1], radius=raio,
                        fill=ext + (255,))
    d.rounded_rectangle([f, f, larg - 1 - f, H - 1 - f], radius=raio - f,
                        fill=interno + (255,))
    d.rounded_rectangle([2 * f, 2 * f, larg - 1 - 2 * f, H - 1 - 2 * f],
                        radius=max(raio - 2 * f, 1), fill=fundo + (255,))
    d.text((pad + larg_txt // 2, H // 2), texto, font=fonte, fill=cor_texto,
           anchor="mm")
    if extra:
        r = int(H * 0.36)
        cx = pad + larg_txt + int(H * 0.12) + r
        d.ellipse([cx - r, H // 2 - r, cx + r, H // 2 + r],
                  fill=(255, 255, 255, 255))
        if youtube:      # mini ícone do YouTube dentro do círculo
            lx, ly = int(r * 0.78), int(r * 0.54)
            d.rounded_rectangle([cx - lx, H // 2 - ly, cx + lx, H // 2 + ly],
                                radius=int(ly * 0.55), fill=(255, 0, 0, 255))
            t = int(ly * 0.55)
            d.polygon([(cx - t * 0.6, H // 2 - t), (cx - t * 0.6, H // 2 + t),
                       (cx + t * 0.95, H // 2)], fill=(255, 255, 255, 255))
        else:
            d.text((cx, H // 2), chip, font=_fonte(int(H * 0.48), True),
                   fill=fundo, anchor="mm")
    return im.resize((larg // S, ALT_SELO), Image.LANCZOS)


def _selo_do_arquivo(chave):
    from PIL import Image
    arq = PASTA_LOGOS / f"{chave}.png"
    if not arq.exists():
        return None
    try:
        im = Image.open(arq).convert("RGBA")
        caixa = im.getchannel("A").getbbox()
        im = im.crop(caixa) if caixa else im
        esc = ALT_SELO / im.height
        larg = min(max(1, round(im.width * esc)), 220)
        return im.resize((larg, ALT_SELO), Image.LANCZOS)
    except Exception:  # noqa
        return None


def _selos_canal(nome):
    """Imagens (selos) de um canal. ESPN com número e ESPN no YouTube têm
    selos próprios; canais desconhecidos viram um selo com o nome."""
    chave = _chave_canal(nome)
    if not chave:
        return []
    if chave in _cache_selos:
        return _cache_selos[chave]
    selos = None
    arq = _selo_do_arquivo(chave)
    if arq is not None:
        selos = [arq]
    elif chave.startswith("espn"):
        resto = chave[4:]
        yt = "youtube" in resto or "brasil" in resto
        m = re.fullmatch(r"(\d)?(?:brasil)?(?:youtube)?", resto)
        if m:
            # ESPN no YouTube = mesmo selo da ESPN numerada, com o ícone do
            # YouTube no círculo no lugar do número
            selos = [_selo_texto("ESPN", (214, 0, 28), (255, 255, 255),
                                 chip=m.group(1), youtube=yt)]
    if selos is None and "youtube" in chave \
            and chave.replace("youtube", "") in CANAIS_VISUAL:
        # canal no YouTube (ex.: TNT Sports): selo do canal + ícone do
        # YouTube no círculo branco, igual ao da ESPN
        texto, fundo, cor = CANAIS_VISUAL[chave.replace("youtube", "")]
        selos = [_selo_texto(texto, fundo, cor, youtube=True)]
    if selos is None and chave in CANAIS_VISUAL:
        texto, fundo, cor = CANAIS_VISUAL[chave]
        selos = [_selo_texto(texto, fundo, cor)]
    if selos is None:
        fundo = _PALETA_GENERICA[sum(map(ord, chave)) % len(_PALETA_GENERICA)]
        selos = [_selo_texto(nome.strip(), fundo, (255, 255, 255))]
    _cache_selos[chave] = selos
    return selos


def selos_da_transmissao(texto):
    """'ESPN4 e Disney+' -> [selo ESPN 4, selo Disney+]."""
    selos = []
    for parte in _dividir_canais(limpar_transmissao(texto)):
        selos += _selos_canal(parte)
    return selos


def _largura_selos(selos):
    return sum(s.width for s in selos) + ESPACO_SELOS * max(len(selos) - 1, 0)


# Agenda: imagem 4:3 de tamanho fixo (1500x1125 = 3x de 500 px de largura).
# A altura das linhas se ajusta ao número de jogos para que tudo caiba.
AGENDA_TAMANHO = (1500, 1125)
AG_COLUNAS_Y = 148            # linha de base do cabeçalho das colunas
AG_CORPO = 170                # onde começa o primeiro dia
AG_BASE = 36                  # margem inferior
AG_H_DIA, AG_GAP_ABRE, AG_GAP_DIA = 38, 14, 18
AG_ALT_MAX, AG_ALT_MIN = 104, 50
# Rodada espalhada por muitos dias: cada dia a mais gasta altura com a faixa do
# dia e os espaços, e o texto das linhas encolhia. Então, quando a rodada tem
# MAIS dias que AG_DIAS_LIMITE, a imagem ganha altura (AG_ALTURA_POR_DIA px por
# dia excedente), até o teto AG_ALTURA_EXTRA_MAX (para não cortar no VK).
# AG_ALTURA_EXTRA_MAX = 0 desliga o recurso (imagem sempre 1500x1125).
AG_DIAS_LIMITE = 3            # até esse número de dias a imagem fica no tamanho normal
AG_ALTURA_POR_DIA = 70        # px de altura somados por dia acima do limite
AG_ALTURA_EXTRA_MAX = 210     # máximo de px somados à altura (teto do ganho)
# jogos em destaque (marcados no painel): a linha mantém a altura normal;
# o rótulo (estrela + texto pequeno) fica no canto superior esquerdo da própria
# linha, acima do horário, com barra e fundo dourados bem suaves
DESTAQUE_ROTULO_PADRAO = "Jogo da Rodada"
DESTAQUE_NO_TEXTO = True       # acrescenta "⭐ rótulo" na linha do texto do fórum


def rotulo_destaque(j):
    return str(j.get("destaque_rotulo") or "").strip() or DESTAQUE_ROTULO_PADRAO


def _estrela(d, cx, cy, R, cor):
    """Estrelinha de cinco pontas (não depende de fonte com o símbolo)."""
    import math
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        r = R if k % 2 == 0 else R * 0.45
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, fill=cor)


def _grupos_por_dia(jogos):
    grupos = []
    for j in jogos:
        dia = j["inicio"].date()
        if grupos and grupos[-1][0] == dia:
            grupos[-1][1].append(j)
        else:
            grupos.append((dia, [j]))
    return grupos


def altura_imagem_agenda(jogos):
    """Altura (px) da imagem da agenda: a normal, mais um extra (limitado) se
    os jogos passarem de AG_DIAS_LIMITE dias. Veja as constantes AG_*."""
    dias = len(_grupos_por_dia(jogos))
    extra = max(0, dias - AG_DIAS_LIMITE) * AG_ALTURA_POR_DIA
    return AGENDA_TAMANHO[1] + max(0, min(AG_ALTURA_EXTRA_MAX, extra))


def altura_linha_agenda(jogos, altura=None):
    """Altura (px) de cada linha de jogo para que todos caibam na imagem
    (altura = altura da imagem; sem ela, a calculada para esses jogos)."""
    grupos = _grupos_por_dia(jogos)
    util = ((altura or altura_imagem_agenda(jogos)) - AG_BASE - AG_CORPO
            - len(grupos) * (AG_H_DIA + AG_GAP_ABRE)
            - (len(grupos) - 1) * AG_GAP_DIA)
    return max(AG_ALT_MIN, min(AG_ALT_MAX, util // max(len(jogos), 1)))


def gerar_agenda_imagem(jogos, titulo, caminho, parte=(1, 1), ref_jogos=None,
                        altura_min=0, alt_linha=None, altura=None):
    """Agenda da rodada (4:3, 1500x1125): tabela com horário, jogo, estádio e
    transmissão. ref_jogos = todos os jogos da rodada (colunas iguais em todas
    as partes); alt_linha = altura da linha (igual em todas as partes)."""
    from PIL import Image, ImageDraw
    W, H = AGENDA_TAMANHO
    H = altura or altura_imagem_agenda(jogos)
    M = 40
    pal = _pal()
    ref = ref_jogos or jogos
    rh = alt_linha or altura_linha_agenda(jogos, H)
    medidor = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    # tamanhos proporcionais à altura da linha (limitados: com poucos jogos
    # a linha fica mais alta, mas as letras não crescem além do ideal)
    rf = min(rh, 82)
    f_cab = _fonte(18, True)
    f_hora = _fonte(int(rf * 0.45), True)
    f_nome_max = int(rf * 0.42)
    f_x = _fonte(int(rf * 0.27), True)
    f_est = _fonte(int(max(20, rf * 0.35)), True)
    esc = int(rf * 0.66)

    # ---- transmissão: selos redimensionados à altura da linha
    usar_logos = CFG.get("tv_logos", True)
    cab_tv = int(medidor.textlength("TRANSMISSÃO", font=f_cab))
    fator = max(28, min(ALT_SELO, int(rf * 0.62))) / ALT_SELO

    def _redim(sel, f):
        return sel.resize((max(1, int(sel.width * f)), max(1, int(sel.height * f))),
                          Image.LANCZOS)

    selos = {}
    if usar_logos:
        for j in ref:
            selos[id(j)] = [_redim(x, fator) for x in
                            selos_da_transmissao(transmissao_exibida(j))]
        W_TV = min(max([_largura_selos(v) for v in selos.values()] + [cab_tv]),
                   280)
        for chave, lista in selos.items():
            if _largura_selos(lista) > W_TV:
                f = (W_TV - ESPACO_SELOS * (len(lista) - 1)) / \
                    sum(x.width for x in lista)
                selos[chave] = [_redim(x, f) for x in lista]
    else:
        W_TV = 260
    X_TV = W - M - 20 - W_TV

    # ---- estádio: largura do maior nome (máx. 280 px; o resto quebra em 2 linhas)
    precisa = max([int(medidor.textlength(j["estadio"], font=f_est)) for j in ref]
                  + [150]) + 8
    W_EST = min(precisa, 310)
    X_EST = X_TV - 30 - W_EST
    X_SEP1, X_SEP2 = X_EST - 15, X_TV - 15

    # ---- horário e bloco do jogo (centralizado entre a hora e o estádio)
    X_HORA = M + 24
    larg_hora = int(medidor.textlength("00h00", font=f_hora))
    X_J0 = X_HORA + larg_hora + 20
    X_J1 = X_SEP1 - 18
    cx = (X_J0 + X_J1) // 2
    folga = esc // 2 + 18                      # centro do "x" -> centro do escudo
    X_ESC1, X_ESC2 = cx - folga, cx + folga
    X_CASA, X_FORA = X_ESC1 - esc // 2 - 12, X_ESC2 + esc // 2 + 12
    LARG_CASA, LARG_FORA = X_CASA - X_J0, X_J1 - X_FORA

    grupos = _grupos_por_dia(jogos)
    y_fim = AG_CORPO + sum(AG_H_DIA + AG_GAP_ABRE + len(js) * rh
                           for _, js in grupos) + (len(grupos) - 1) * AG_GAP_DIA
    vazio = None
    if (H - AG_BASE) - y_fim >= 130 and CFG.get("logo_no_vazio", True) \
            and not _logo_grande_ativo():
        vazio = (y_fim + 16, H - AG_BASE - 6)

    img = Image.new("RGB", (W, H), pal["bg"])
    _textura_fundo(img, excluir_y=vazio)
    d = ImageDraw.Draw(img)
    _faixa_topo(d, W)

    # ---- cabeçalho: logo + título (e "n/total" se a agenda for dividida)
    xt, xs = _logo_cabecalho(img, M + 6, 36, 42, 100, 108, "agenda")
    reserva = 120 if parte[1] > 1 else 0
    d.text((xt, 42), titulo,
           font=_fonte_ajustada(d, titulo, W - M - 6 - xt - reserva, 56),
           fill=pal["txt"])
    if parte[1] > 1:
        txt_p = f"{parte[0]}/{parte[1]}"
        f_p = _fonte(28, True)
        lp = int(d.textlength(txt_p, font=f_p)) + 36
        _caixa(img, [W - M - lp, 52, W - M, 96], pal["cartao"], 0.92, raio=22)
        d.text((W - M - lp // 2, 74), txt_p, font=f_p, fill=pal["suave"],
               anchor="mm")

    # ---- cabeçalho das colunas
    d.text((X_HORA, AG_COLUNAS_Y), "HORA (BRASÍLIA)", font=f_cab, fill=pal["cab"], anchor="ls")
    d.text((cx, AG_COLUNAS_Y), "JOGO", font=f_cab, fill=pal["cab"], anchor="ms")
    d.text((X_EST, AG_COLUNAS_Y), "ESTÁDIO", font=f_cab, fill=pal["cab"],
           anchor="ls")
    d.text((X_TV, AG_COLUNAS_Y), "TRANSMISSÃO", font=f_cab, fill=pal["cab"],
           anchor="ls")
    d.line([M, AG_COLUNAS_Y + 10, W - M, AG_COLUNAS_Y + 10], fill=pal["linha"],
           width=2)

    y = AG_CORPO
    for dia, js in grupos:
        # faixa do dia
        _caixa(img, [M, y, W - M, y + AG_H_DIA - 1], pal["cartao"], 0.92, raio=10)
        d.rounded_rectangle([M, y, M + 8, y + AG_H_DIA - 1], radius=4,
                            fill=_cor_destaque())
        d.text((M + 28, y + AG_H_DIA // 2),
               f"{DIAS[dia.weekday()]}, {dia.day} {MESES[dia.month]} {dia.year}",
               font=_fonte(24, True), fill=pal["txt"], anchor="lm")
        y += AG_H_DIA + AG_GAP_ABRE

        for i, j in enumerate(js):
            cy = y + rh // 2
            if j.get("destaque"):
                ouro = pal["ouro"]
                _caixa(img, [M, y, W - M, y + rh - 1], ouro, 0.13, raio=10)
                d.rounded_rectangle([M, y, W - M, y + rh - 1], radius=10,
                                    outline=ouro, width=3)
                f_pil = _fonte(16, True)
                txt = rotulo_destaque(j).upper()
                R_EST = 7
                lp = int(d.textlength(txt, font=f_pil)) + 2 * 14 + 2 * R_EST + 6
                x0p, y0p = M + 24, y - 14
                d.rounded_rectangle([x0p, y0p, x0p + lp, y0p + 22], radius=11,
                                    fill=ouro)
                _estrela(d, x0p + 14 + R_EST, y0p + 11, R_EST, (25, 25, 25))
                d.text((x0p + 14 + 2 * R_EST + 6, y0p + 11), txt, font=f_pil,
                       fill=(25, 25, 25), anchor="lm")
            elif i % 2 == 1:
                _caixa(img, [M, y, W - M, y + rh - 1], pal["zebra_jogo"], 0.75,
                       raio=8)
            for xs_ in (X_SEP1, X_SEP2):
                d.line([xs_, y + 12, xs_, y + rh - 13], fill=pal["divisor"],
                       width=2)
            d.text((X_HORA, cy), j["hora"], font=f_hora, fill=pal["ouro"],
                   anchor="lm")
            d.text((X_CASA, cy), j["mandante"],
                   font=_fonte_ajustada(d, j["mandante"], LARG_CASA, f_nome_max,
                                        minimo=16),
                   fill=pal["txt"], anchor="rm")
            desenhar_escudo(img, X_ESC1, cy, esc, j["mandante"],
                            j.get("mandante_id"))
            d.text((cx, cy), "x", font=f_x, fill=pal["cab"], anchor="mm")
            desenhar_escudo(img, X_ESC2, cy, esc, j["visitante"],
                            j.get("visitante_id"))
            d.text((X_FORA, cy), j["visitante"],
                   font=_fonte_ajustada(d, j["visitante"], LARG_FORA, f_nome_max,
                                        minimo=16),
                   fill=pal["txt"], anchor="lm")
            _texto_coluna(d, j["estadio"], X_EST, cy, W_EST, pal["txt"],
                          tam=int(max(20, rf * 0.35)), negrito=True)
            if usar_logos:
                x = X_TV
                for selo in selos[id(j)]:
                    img.paste(selo, (x, cy - selo.height // 2), selo)
                    x += selo.width + ESPACO_SELOS
            else:
                _texto_coluna(d, transmissao_exibida(j), X_TV, cy, W_TV,
                              pal["txt"], tam=int(max(20, rf * 0.35)),
                              negrito=True)
            y += rh
        y += AG_GAP_DIA

    if vazio:
        _preencher_vazio(img, *vazio)
    img.save(caminho)


# --------------------------------------------------------------------------
# AGENDA EM VÁRIAS IMAGENS
# --------------------------------------------------------------------------
MAX_JOGOS_IMAGEM = 10


def dividir_jogos(jogos, maximo=MAX_JOGOS_IMAGEM):
    """Divide a lista em partes de tamanho parecido, cortando de preferência
    na virada do dia (ex.: 18 jogos -> 9 de terça + 9 de quarta)."""
    n = len(jogos)
    if n <= maximo:
        return [jogos]
    partes = -(-n // maximo)
    limites = [i for i in range(1, n)
               if jogos[i]["inicio"].date() != jogos[i - 1]["inicio"].date()]
    cortes, anterior = [], 0
    for k in range(1, partes):
        ideal = round(k * n / partes)
        corte = min(limites, key=lambda i: abs(i - ideal)) if limites else ideal
        if abs(corte - ideal) > 3 or corte <= anterior:
            corte = max(ideal, anterior + 1)
        cortes.append(corte)
        anterior = corte
    pontos = [0] + cortes + [n]
    return [jogos[pontos[i]:pontos[i + 1]] for i in range(len(pontos) - 1)]


def gerar_agendas(jogos, titulo, pasta):
    """Gera agenda.png (ou agenda_1.png, agenda_2.png... se forem muitos
    jogos, com 'n/total' no topo). Todas as partes saem com o mesmo tamanho
    (4:3) e a mesma altura de linha. Retorna a lista de arquivos."""
    for velho in list(pasta.glob("agenda*.png")) + list(pasta.glob("f2_agenda*.png")):
        try:
            velho.unlink()
        except OSError:
            pass
    partes = dividir_jogos(jogos)
    # todas as partes com a mesma altura (a da parte com mais dias)
    altura = max(altura_imagem_agenda(p) for p in partes)
    alt = min(altura_linha_agenda(p, altura) for p in partes)
    caminhos = []
    for i, parte in enumerate(partes, start=1):
        nome = "agenda.png" if len(partes) == 1 else f"agenda_{i}.png"
        gerar_agenda_imagem(parte, titulo, pasta / nome, (i, len(partes)),
                            ref_jogos=jogos, alt_linha=alt, altura=altura)
        caminhos.append(pasta / nome)
    return caminhos


# --------------------------------------------------------------------------
# IMAGEM DO JOGO DA RODADA  (sem texto: escudos + cores de cada clube)
# --------------------------------------------------------------------------
IMG_JOGO_TAMANHO = (1600, 640)   # largura x altura (proporção ~2,5:1)
IMG_JOGO_ESCUDO = 0.52           # lado da caixa do escudo / altura da imagem
IMG_JOGO_INCLINACAO = 0.16       # inclinação da divisória (fração da altura)
DESTAQUE_LOGO_ALFA = 0.11        # opacidade do logo da competição no fundo
DESTAQUE_LOGO_TAMANHO = 1.30     # altura do logo / altura da caixa (>1 = cortado)
_GRAFITE = (52, 57, 68)


def _candidatos_cor(escudo):
    """Cores do escudo que servem de fundo, da mais presente para a menos.
    Ignora branco, preto e cinza; amarelo/dourado conta menos (some atrás
    do próprio escudo). None no fim da lista = 'grafite' (escudos com muito
    preto, ou sem nenhuma cor aproveitável)."""
    import colorsys
    if escudo is None:
        return [None]
    im = escudo.copy()
    im.thumbnail((96, 96))
    faixas, total, escuros = {}, 0, 0
    for r, g, b, a in im.getdata():
        if a < 200:
            continue
        total += 1
        h, l, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if l < 0.20:
            escuros += 1
        if sat < 0.30 or l > 0.82 or l < 0.12:
            continue
        peso = sat * (1.0 - 0.45 * abs(l - 0.40))
        if 0.10 <= h <= 0.19:                    # amarelo / dourado
            peso *= 0.15
        k = int(h * 24) % 24
        acum = faixas.setdefault(k, [0.0, 0, 0, 0, 0])
        acum[0] += peso
        acum[1] += r
        acum[2] += g
        acum[3] += b
        acum[4] += 1
    cores = []
    if faixas:
        ordem = sorted(faixas.values(), key=lambda v: -v[0])
        topo = ordem[0][0]
        cores = [(round(v[1] / v[4]), round(v[2] / v[4]), round(v[3] / v[4]))
                 for v in ordem if v[0] >= 0.35 * topo][:3]
    if not cores or (total and escuros / total >= 0.10):
        cores.append(None)
    return cores


def _tom_fundo(rgb, brilho=None):
    """Versão do tom do clube boa para fundo: escura e rica, com o brilho
    controlado para o escudo e o logo aparecerem. None = grafite."""
    import colorsys
    if rgb is None:
        return _GRAFITE
    h, l, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    sat = max(0.40, min(0.85, sat))
    if brilho is not None:
        l = brilho
    elif 0.10 <= h <= 0.19:                  # amarelo/dourado: tom vivo, não
        l, sat = max(0.40, min(0.48, l)), max(sat, 0.85)    # "barro"
    else:
        l = max(0.24, min(0.38, l))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, sat))


def _dif_tons(a, b):
    """Quão diferentes dois tons de fundo parecem (cor + saturação + brilho)."""
    import colorsys
    ha, la, sa = colorsys.rgb_to_hls(*(c / 255 for c in a))
    hb, lb, sb = colorsys.rgb_to_hls(*(c / 255 for c in b))
    rgb = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    return rgb + 120 * abs(sa - sb) + 200 * abs(la - lb)


def _tons_do_jogo(esc_a, esc_b):
    """Tom de fundo dos dois clubes. Usa a cor principal de cada um; se
    ficarem parecidos (azul x azul), tenta outra cor do escudo (inclusive
    grafite, quando o escudo tem muito preto). Se não houver outra opção,
    separa pelo brilho: um fica bem escuro e o outro mais claro."""
    A = [(c, _tom_fundo(c)) for c in _candidatos_cor(esc_a)]
    B = [(c, _tom_fundo(c)) for c in _candidatos_cor(esc_b)]
    pares = sorted((i + j, i, j) for i in range(len(A)) for j in range(len(B)))
    for _, i, j in pares:
        if _dif_tons(A[i][1], B[j][1]) >= 100:
            return A[i][1], B[j][1]
    (ca, ta), (cb, tb) = A[0], B[0]
    return _tom_fundo(ca, 0.20), _tom_fundo(cb, 0.46)


def _fundo_caixa(w, h, tom, logo=None, inclina=0):
    """Fundo de uma caixa: brilho leve no centro e bordas mais escuras, faixas
    diagonais bem suaves (na mesma inclinação da divisória) e (opcional) o logo
    da competição em baixa opacidade."""
    from PIL import Image, ImageDraw
    claro = tuple(min(255, round(c + (255 - c) * 0.12)) for c in tom)
    escuro = tuple(round(c * 0.66) for c in tom)
    mascara = Image.radial_gradient("L").resize((w, h), Image.BICUBIC)
    mascara = mascara.point(lambda v: min(255, round(v * 1.15)))
    img = Image.composite(Image.new("RGB", (w, h), escuro),
                          Image.new("RGB", (w, h), claro), mascara)
    faixas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(faixas)
    for x0, x1, alfa in ((0.10, 0.30, 15), (0.34, 0.40, 11), (0.62, 0.92, 13)):
        fd.polygon([(w * x0 - inclina / 2, h), (w * x1 - inclina / 2, h),
                    (w * x1 + inclina / 2, 0), (w * x0 + inclina / 2, 0)],
                   fill=(255, 255, 255, alfa))
    img = img.convert("RGBA")
    img.alpha_composite(faixas)
    if logo is not None:
        lado = int(h * DESTAQUE_LOGO_TAMANHO)
        esc = lado / max(logo.size)             # também amplia logos pequenos
        lg = logo.resize((max(1, round(logo.width * esc)),
                          max(1, round(logo.height * esc))), Image.LANCZOS)
        lg = _logo_branco(lg)
        lg.putalpha(lg.getchannel("A").point(
            lambda v: round(v * DESTAQUE_LOGO_ALFA)))
        camada = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        camada.paste(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
        img.alpha_composite(camada)         # o que passa da caixa é cortado
    return img.convert("RGB")


def _colar_escudo_com_sombra(img, cx, cy, diam, escudo):
    """Escudo real com uma sombra bem leve embaixo (dá profundidade, sem
    brilho). Mesmo tamanho útil que _colar_escudo."""
    from PIL import Image, ImageChops, ImageFilter
    pequeno = _escudo_no_tamanho(escudo, diam)
    x = int(cx - pequeno.width / 2)
    y = (int(cy - pequeno.height / 2)
         + _deslocamento_vertical_escudo(escudo, pequeno))
    sombra = Image.new("L", img.size, 0)
    sombra.paste(pequeno.getchannel("A"), (x, y))
    sombra = ImageChops.offset(sombra.filter(ImageFilter.GaussianBlur(11)),
                               0, 12).point(lambda v: round(v * 0.34))
    img.paste((0, 0, 0), (0, 0), sombra)
    img.paste(pequeno, (x, y), pequeno)


def gerar_imagem_jogo(j, caminho):
    """Imagem sem texto para um jogo: duas áreas separadas por uma diagonal,
    cada uma com o fundo na cor do clube e o escudo (mesmo tamanho)
    centralizado na sua área."""
    from PIL import Image, ImageDraw
    W, H = IMG_JOGO_TAMANHO
    desloc = int(H * IMG_JOGO_INCLINACAO)           # a divisória vai de
    centros = (W // 4, 3 * W // 4)                  # (W/2+desloc, 0) a (W/2-desloc, H)
    ids = (j.get("mandante_id"), j.get("visitante_id"))
    escudos = [_carregar_escudo(i) if i else None for i in ids]
    tons = list(_tons_do_jogo(*escudos))
    for i, chave in enumerate(("cor_mandante", "cor_visitante")):
        if _cor_hex_valida(j.get(chave)):      # cor escolhida no painel
            tons[i] = _hex_rgb(j[chave].strip())
    logo = None
    if CFG.get("destaque_logo_fundo", True):
        try:
            logo = _logo_competicao()
        except Exception:  # noqa
            logo = None

    img = Image.new("RGB", (W, H))
    largura_fundo = W // 2 + 2 * desloc
    for i in range(2):
        fundo = _fundo_caixa(largura_fundo, H, tons[i], logo, 2 * desloc)
        camada = Image.new("RGB", (W, H), tons[i])
        camada.paste(fundo, (centros[i] - largura_fundo // 2, 0))
        if i == 0:
            img = camada
        else:                                       # recorta pela diagonal
            S = 3
            m = Image.new("L", (W * S, H * S), 0)
            ImageDraw.Draw(m).polygon(
                [((W // 2 + desloc) * S, 0), (W * S, 0), (W * S, H * S),
                 ((W // 2 - desloc) * S, H * S)], fill=255)
            img.paste(camada, (0, 0), m.resize((W, H), Image.LANCZOS))

    # linha divisória: faixa translúcida + traço branco fino
    S = 3
    linha = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(linha)
    p0, p1 = ((W // 2 + desloc) * S, 0), ((W // 2 - desloc) * S, H * S)
    ld.line([p0, p1], fill=(255, 255, 255, 36), width=34 * S)
    ld.line([p0, p1], fill=(255, 255, 255, 215), width=5 * S)
    linha = linha.resize((W, H), Image.LANCZOS)
    img = Image.alpha_composite(img.convert("RGBA"), linha).convert("RGB")

    diam = int(H * IMG_JOGO_ESCUDO)
    nomes = (j.get("mandante", ""), j.get("visitante", ""))
    for i in range(2):
        cx, cy = centros[i], H // 2
        escudo = escudos[i]
        if escudo is not None:
            _colar_escudo_com_sombra(img, cx, cy, diam, escudo)
        else:
            _desenhar_botao(img, cx, cy, diam, nomes[i])
    img.save(caminho)


def tons_automaticos(j):
    """Cores de fundo que o programa escolheria (hex), para servir de ponto
    de partida ao escolher uma cor à mão."""
    ids = (j.get("mandante_id"), j.get("visitante_id"))
    escudos = [_carregar_escudo(i) if i else None for i in ids]
    return tuple("#%02x%02x%02x" % t for t in _tons_do_jogo(*escudos))


def gerar_imagens_destaque(jogos, pasta):
    """Uma imagem por jogo marcado como destaque: destaque.png (ou
    destaque_1.png, destaque_2.png...). Apaga as antigas. Retorna a lista."""
    for velho in pasta.glob("destaque*.png"):
        try:
            velho.unlink()
        except OSError:
            pass
    sel = [j for j in jogos if j.get("destaque")]
    caminhos = []
    for i, j in enumerate(sel, start=1):
        nome = "destaque.png" if len(sel) == 1 else f"destaque_{i}.png"
        gerar_imagem_jogo(j, pasta / nome)
        caminhos.append(pasta / nome)
    return caminhos


# --------------------------------------------------------------------------
# RESULTADOS DA RODADA  (imagem só com os placares: sem datas nem horários)
# --------------------------------------------------------------------------
RES_TAMANHO = (1080, 1440)      # mesma proporção da imagem de classificação
RES_TOPO, RES_BASE = 280, 60    # onde a lista começa / margem inferior
RES_DESTACAR_VENCEDOR = False   # (não usado: o placar tem uma cor só, a do fundo da competição)
PASTA_FONTES = PASTA_BASE / "fontes"
RES_ALT_MAX, RES_ALT_MIN = 170, 78   # altura de cada linha (px)
RES_MARGEM = 44                 # margem lateral da caixa de resultados (px)
RES_PAD = 14                    # folga dentro da caixa, acima/abaixo das linhas
_LARANJA = (245, 140, 30)
_VERMELHO = (222, 52, 62)

# status do Sofascore -> (situação, texto do selo). Jogos que ainda não
# aconteceram (ou não vão acontecer) trocam o placar por um selo.
_STATUS_RESULTADO = {
    "finished": ("final", ""),
    "inprogress": ("vivo", "AO VIVO"),
    "notstarted": ("agendado", "A JOGAR"),
    "postponed": ("adiado", "ADIADO"),
    "canceled": ("cancelado", "CANCELADO"),
    "cancelled": ("cancelado", "CANCELADO"),
    "interrupted": ("interrompido", "INTERROMPIDO"),
    "suspended": ("interrompido", "SUSPENSO"),
    "abandoned": ("interrompido", "SUSPENSO"),
}


def _placar_evento(ev, lado):
    """(gols, pênaltis) de um lado ('home'/'away'); None quando não há."""
    s_ = ev.get(f"{lado}Score") or {}
    v = s_.get("display")
    if v is None:
        v = s_.get("current")
    pen = s_.get("penalties")
    return (v if isinstance(v, int) else None,
            pen if isinstance(pen, int) else None)


def buscar_resultados(rodada, debug_dir=None):
    """Jogos da rodada com placar e situação (uma só consulta ao Sofascore).
    Mesma ordem da agenda, para a divisão em imagens ser idêntica."""
    dados = get(caminho_eventos(rodada), "resultados_rodada", debug_dir)
    eventos = sorted(dados.get("events", []), key=lambda e: e["startTimestamp"])
    if not eventos:
        raise RuntimeError("Nenhum jogo encontrado para essa rodada.")
    jogos = []
    for ev in eventos:
        gm, pm = _placar_evento(ev, "home")
        gv, pv = _placar_evento(ev, "away")
        situacao, rotulo = _STATUS_RESULTADO.get(
            str((ev.get("status") or {}).get("type") or "").lower(),
            ("agendado", "A JOGAR"))
        jogos.append({
            "inicio": datetime.fromtimestamp(ev["startTimestamp"], FUSO),
            "mandante": nome_time(ev["homeTeam"]["name"]),
            "visitante": nome_time(ev["awayTeam"]["name"]),
            "mandante_id": ev["homeTeam"].get("id"),
            "visitante_id": ev["awayTeam"].get("id"),
            "situacao": situacao, "rotulo": rotulo,
            "gols_m": gm, "gols_v": gv, "pen_m": pm, "pen_v": pv,
        })
    return jogos


def _tem_placar(j):
    return (j["situacao"] in ("final", "vivo", "interrompido")
            and j["gols_m"] is not None and j["gols_v"] is not None)


def _vencedor(j):
    """'m', 'v' ou None (empate / sem placar). Pênaltis desempatam."""
    if not _tem_placar(j):
        return None
    if j["gols_m"] != j["gols_v"]:
        return "m" if j["gols_m"] > j["gols_v"] else "v"
    pm, pv = j.get("pen_m"), j.get("pen_v")
    if pm is not None and pv is not None and pm != pv:
        return "m" if pm > pv else "v"
    return None


def _altura_linha_resultados(n):
    util = RES_TAMANHO[1] - RES_TOPO - RES_BASE - 2 * RES_PAD
    return max(RES_ALT_MIN, min(RES_ALT_MAX, util // max(n, 1)))


def _pilula(d, cx, cy, texto, fundo, cor_texto, tam, larg_max=None):
    """Selo arredondado centralizado em (cx, cy); encolhe se passar de larg_max."""
    while True:
        f = _fonte(tam, True)
        w = int(d.textlength(texto, font=f)) + int(tam * 1.4)
        if larg_max is None or w <= larg_max or tam <= 13:
            break
        tam -= 1
    h = int(tam * 1.75)
    d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                        radius=h // 2, fill=fundo)
    d.text((cx, cy), texto, font=f, fill=cor_texto, anchor="mm")


def _fonte_titulo(tamanho):
    """Fonte de destaque dos títulos. Para usar outra, salve o arquivo da
    fonte na pasta 'fontes' com o nome titulo.ttf (ou titulo.otf). Sem isso,
    usa a Impact do Windows (ou Arial Black) e, por fim, a fonte padrão."""
    from PIL import ImageFont
    for cand in (PASTA_FONTES / "titulo.ttf", PASTA_FONTES / "titulo.otf",
                 "impact.ttf", "Impact.ttf", "ariblk.ttf"):
        try:
            return ImageFont.truetype(str(cand), tamanho)
        except OSError:
            continue
    return _fonte(tamanho, True)


def _texto_espacado(d, cx, cy, texto, fonte, cor, espaco):
    """Texto em maiúsculas com espaço extra entre as letras, centralizado em
    (cx, cy) tanto na horizontal quanto na vertical."""
    larguras = [d.textlength(c, font=fonte) for c in texto]
    total = sum(larguras) + espaco * (len(texto) - 1)
    _l, topo, _r, base = d.textbbox((0, 0), "H", font=fonte, anchor="ls")
    y_base = cy - topo / 2                          # linha de base (topo < 0)
    x = cx - total / 2
    for c, w in zip(texto, larguras):
        d.text((x, y_base), c, font=fonte, fill=cor, anchor="ls")
        x += w + espaco


def _escudo_esmaecido(img, cx, cy, diam, nome, team_id, forca=1.0):
    """Escudo normal (forca=1) ou misturado com o fundo (jogo sem placar)."""
    from PIL import Image
    if forca >= 1.0:
        desenhar_escudo(img, cx, cy, diam, nome, team_id)
        return
    r = diam // 2 + 6
    caixa = (int(cx - r), int(cy - r), int(cx + r), int(cy + r))
    antes = img.crop(caixa)
    desenhar_escudo(img, cx, cy, diam, nome, team_id)
    img.paste(Image.blend(antes, img.crop(caixa), forca), caixa)


def _cor_placar(pal):
    """Cor do placar: o mesmo matiz do fundo da competição, bem clara e viva
    (tema claro: versão escura), para combinar em vez de usar um dourado fixo."""
    import colorsys
    r, g, b = (c / 255 for c in pal["bg"][:3])
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    if pal.get("modo") == "claro":
        return _hls(h, 0.28, 0.80)
    return _hls(h, 0.82, 0.85)


def gerar_resultados_imagem(jogos, subtitulo, caminho, rh):
    """Resultados de até ~10 jogos (1080x1440, como a classificação): título
    RESULTADOS (fonte de destaque) centralizado, uma linha com o logo e o nome
    da rodada e, abaixo, uma caixa com um jogo por linha, separados por linhas
    que somem nas pontas: NOME DO MANDANTE + escudo | placar | escudo + NOME DO
    VISITANTE (nomes em maiúsculas). Jogo sem placar mostra um selo (A JOGAR,
    ADIADO, CANCELADO...) e escudos esmaecidos; jogo em andamento mostra o
    placar parcial com o selo AO VIVO."""
    from PIL import Image, ImageDraw
    W, H = RES_TAMANHO
    pal = _pal()
    img = Image.new("RGB", (W, H), pal["bg"])
    _textura_fundo(img)
    d = ImageDraw.Draw(img)
    _faixa_topo(d, W)

    # ---- título: RESULTADOS (fonte de destaque, letras espaçadas)
    titulo = "RESULTADOS"
    tam = 124
    while True:
        f_tit = _fonte_titulo(tam)
        esp = max(4, int(tam * 0.06))
        larg = sum(d.textlength(c, font=f_tit) for c in titulo) \
            + esp * (len(titulo) - 1)
        if larg <= W - 140 or tam <= 40:
            break
        tam -= 4
    _texto_espacado(d, W // 2, 104, titulo, f_tit, pal["txt"], esp)

    # ---- subtítulo: [logo na cor dele] Competição - Rodada • n/total
    logo = _logo_para_cabecalho(50, "auto")
    gap = 15
    reserva = (logo.width + gap) if logo else 0
    f_sub = _fonte_ajustada(d, subtitulo, W - 100 - reserva, 31,
                            negrito=False, minimo=20)
    x = (W - (reserva + int(d.textlength(subtitulo, font=f_sub)))) // 2
    cy_sub = 213
    if logo:
        img.paste(logo, (x, cy_sub - logo.height // 2), logo)
        x += reserva
    d.text((x, cy_sub), subtitulo, font=f_sub, fill=pal["txt2"], anchor="lm")

    # ---- medidas (proporcionais à altura da linha)
    n = len(jogos)
    cx = W // 2
    diam = min(int(rh * 0.70), 88)
    fs = min(int(rh * 0.50), 64)
    f_placar = _fonte(fs, True)
    f_pen = _fonte(max(16, int(rh * 0.16)), True)
    tam_sel_g = max(18, min(int(rh * 0.19), 26))   # selo no lugar do placar
    tam_sel_p = max(14, int(rh * 0.14))            # selo sob o placar
    cores_selo = {"vivo": _VERMELHO, "cancelado": _VERMELHO,
                  "adiado": _LARANJA, "interrompido": _LARANJA}
    cor_pl = _cor_placar(pal)

    # meia-largura reservada ao placar (cabe o maior, ex.: "10-0")
    larg_placar = max([d.textlength(f"{j['gols_m']}-{j['gols_v']}", font=f_placar)
                       for j in jogos if _tem_placar(j)] + [fs * 1.9]) + 32
    sh = int(larg_placar / 2) + 10
    off = sh + 8 + diam // 2                     # centro do escudo ao centro

    # ---- caixa que guarda todas as linhas
    x0c, x1c = RES_MARGEM, W - RES_MARGEM
    util = H - RES_TOPO - RES_BASE
    y0c = RES_TOPO + max(0, (util - rh * n - 2 * RES_PAD) // 2)
    y1c = y0c + rh * n + 2 * RES_PAD
    _caixa(img, [x0c, y0c, x1c, y1c], pal["cartao"], 0.92, raio=28)
    d = ImageDraw.Draw(img)

    # ---- nomes: tamanho comum (o maior que cabe na maioria); só o nome que
    # ainda assim não couber encolhe sozinho, para os demais não ficarem pequenos
    larg_nome = (cx - off - diam // 2 - 18) - (x0c + 30)
    tam_max_nome = max(20, min(int(rh * 0.36), 44))
    tam_nome = tam_max_nome
    while tam_nome > 30 and any(
            d.textlength(j[k].upper(), font=_fonte(tam_nome, True)) > larg_nome
            for j in jogos for k in ("mandante", "visitante")):
        tam_nome -= 1
    f_nome = _fonte(tam_nome, True)

    def _fonte_do_nome(texto):
        t = tam_nome
        while t > 16 and d.textlength(texto, font=_fonte(t, True)) > larg_nome:
            t -= 1
        return _fonte(t, True)

    # ---- divisórias que somem nas pontas (camada com transparência)
    camada = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dc = ImageDraw.Draw(camada)
    xa, xb = x0c + 36, x1c - 36
    fade = (xb - xa) // 3
    r_, g_, b_ = pal["linha"][:3]
    for i in range(n - 1):
        yl = y0c + RES_PAD + (i + 1) * rh
        for xx in range(xa, xb + 1):
            a = int(255 * min(1.0, min(xx - xa, xb - xx) / fade))
            dc.line([xx, yl, xx, yl + 1], fill=(r_, g_, b_, a))
    img.paste(camada.convert("RGB"), (0, 0), camada.split()[3])
    d = ImageDraw.Draw(img)

    # ---- as linhas
    for i, j in enumerate(jogos):
        cy = y0c + RES_PAD + i * rh + rh // 2
        jogou = _tem_placar(j)
        forca = 1.0 if jogou else 0.5
        cor_nome = pal["txt"] if jogou else pal["txt2"]
        _escudo_esmaecido(img, cx - off, cy, diam, j["mandante"],
                          j.get("mandante_id"), forca)
        _escudo_esmaecido(img, cx + off, cy, diam, j["visitante"],
                          j.get("visitante_id"), forca)
        d.text((cx - off - diam // 2 - 18, cy), j["mandante"].upper(),
               font=_fonte_do_nome(j["mandante"].upper()), fill=cor_nome,
               anchor="rm")
        d.text((cx + off + diam // 2 + 18, cy), j["visitante"].upper(),
               font=_fonte_do_nome(j["visitante"].upper()), fill=cor_nome,
               anchor="lm")

        if jogou:
            penaltis = (j["situacao"] == "final" and j["pen_m"] is not None
                        and j["pen_v"] is not None)
            embaixo = penaltis or j["situacao"] != "final"
            cyp = cy - int(rh * 0.09) if embaixo else cy
            d.text((cx - 16, cyp), str(j["gols_m"]), font=f_placar,
                   anchor="rm", fill=cor_pl)
            d.text((cx, cyp), "-", font=f_placar, anchor="mm", fill=cor_pl)
            d.text((cx + 16, cyp), str(j["gols_v"]), font=f_placar,
                   anchor="lm", fill=cor_pl)
            if penaltis:
                d.text((cx, cy + int(rh * 0.30)),
                       f"Pên. {j['pen_m']} x {j['pen_v']}", font=f_pen,
                       fill=pal["suave"], anchor="mm")
            elif j["situacao"] != "final":
                _pilula(d, cx, cy + int(rh * 0.30), j["rotulo"],
                        cores_selo.get(j["situacao"], pal["linha"]),
                        (255, 255, 255), tam_sel_p, larg_max=2 * sh)
        else:
            _pilula(d, cx, cy, j["rotulo"] or "ENCERRADO",
                    cores_selo.get(j["situacao"], pal["linha"]),
                    (255, 255, 255) if j["situacao"] in cores_selo
                    else pal["txt2"], tam_sel_g, larg_max=2 * sh + 16)
    img.save(caminho)


def gerar_resultados(jogos, rodada, pasta):
    """resultados.png (ou resultados_1.png, resultados_2.png... quando a
    agenda também é dividida: mesma regra de divisão). Retorna os caminhos."""
    for velho in pasta.glob("resultados*.png"):
        try:
            velho.unlink()
        except OSError:
            pass
    partes = dividir_jogos(jogos)
    rh = min(_altura_linha_resultados(len(p)) for p in partes)
    base = f"{CFG['nome_curto']} - {rotulo_rodada(rodada)}"
    caminhos = []
    for i, parte in enumerate(partes, start=1):
        nome = "resultados.png" if len(partes) == 1 else f"resultados_{i}.png"
        sub = base + (f" • {i}/{len(partes)}" if len(partes) > 1 else "")
        gerar_resultados_imagem(parte, sub, pasta / nome, rh)
        caminhos.append(pasta / nome)
    return caminhos


def atualizar_resultados(rodada, pasta, debug_dir=None):
    """Busca os placares, refaz a(s) imagem(ns) e grava resultados.json.
    Retorna (caminhos, jogos encerrados, total de jogos)."""
    jogos = buscar_resultados(rodada, debug_dir)
    caminhos = gerar_resultados(jogos, rodada, pasta)
    encerrados = sum(1 for j in jogos if j["situacao"] == "final")
    (pasta / "resultados.json").write_text(json.dumps({
        "atualizado": datetime.now(FUSO).isoformat(timespec="seconds"),
        "rotulo": rotulo_rodada(rodada), "encerrados": encerrados,
        "jogos": [{**j, "inicio": j["inicio"].isoformat()} for j in jogos],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminhos, encerrados, len(jogos)


# --------------------------------------------------------------------------
# CLASSIFICAÇÃO POR GRUPOS E CHAVEAMENTO (mata-mata)
# --------------------------------------------------------------------------
def _titulo_grupo(nome):
    t = (nome or "").strip()
    m = re.fullmatch(r"(?i)group\s+(\w+)", t)
    return f"Grupo {m.group(1).upper()}" if m else (t or "Grupo")


def gerar_classificacao_grupos(grupos, pasta, subtitulo):
    """Várias tabelas pequenas (uma por grupo), 4 grupos por imagem."""
    from PIL import Image, ImageDraw
    POR_IMAGEM = 4
    blocos = [grupos[i:i + POR_IMAGEM] for i in range(0, len(grupos), POR_IMAGEM)]
    W, MARGEM, TOPO = 1080, 50, 180
    LH, ALT_CAB, GAP = 46, 58, 24
    COL = {"J": 470, "V": 540, "E": 610, "D": 680, "GP": 765, "GC": 845,
           "SG": 930, "PTS": W - MARGEM - 8}
    X_POS, X_ESCUDO, X_NOME = MARGEM + 40, MARGEM + 90, MARGEM + 130
    cor_dest = _cor_destaque()

    for bi, bloco in enumerate(blocos, start=1):
        info = []
        for g in bloco:
            linhas = sorted(g["rows"], key=lambda r: r["position"])
            zonas, meta = zonas_da_tabela(linhas)
            info.append((g, linhas, zonas, meta))
        H = TOPO + sum(ALT_CAB + LH * len(l) + GAP for _g, l, _z, _m in info) + 110
        img = Image.new("RGB", (W, H), _pal()["bg"])
        _textura_fundo(img)
        d = ImageDraw.Draw(img)
        _faixa_topo(d, W)
        xt, xs = _logo_cabecalho(img, MARGEM + 20, 36, 36, 88, 134,
                                 "classificacao")
        d.text((xt, 36), "Classificação", font=_fonte(52, True),
               fill=_pal()["txt"])
        sub = subtitulo + (f" • {bi}/{len(blocos)}" if len(blocos) > 1 else "")
        d.text((xs, 104), sub, font=_fonte(26), fill=_pal()["suave"])

        f_cab, f_nome = _fonte(19, True), _fonte(25, True)
        f_num, f_pts = _fonte(24), _fonte(26, True)
        usadas = {}
        y = TOPO
        for g, linhas, zonas, meta in info:
            h_cab = ALT_CAB - 8
            _caixa(img, [MARGEM - 20, y, W - MARGEM + 20, y + h_cab],
                   _pal()["cartao"], 0.90, raio=12)
            d.rounded_rectangle([MARGEM - 20, y, MARGEM - 12, y + h_cab],
                                radius=4, fill=cor_dest)
            d.text((MARGEM + 10, y + h_cab // 2), _titulo_grupo(g.get("name")),
                   font=_fonte(28, True), fill=_pal()["txt"], anchor="lm")
            for nome, x in COL.items():
                d.text((x, y + h_cab // 2), nome, font=f_cab,
                       fill=_pal()["cab"], anchor="rm")
            y0 = y + ALT_CAB
            for i, r in enumerate(linhas):
                yy = y0 + i * LH
                if i % 2 == 1:
                    _caixa(img, [MARGEM - 20, yy, W - MARGEM + 20, yy + LH - 3],
                           _pal()["linha_alt"], 0.70)
                cy = yy + (LH - 3) // 2
                d.text((X_POS, cy), str(r["position"]), font=f_nome,
                       fill=_pal()["suave"], anchor="rm")
                desenhar_escudo(img, X_ESCUDO + 5, cy, 32, r["team"]["name"],
                                r["team"].get("id"))
                d.text((X_NOME, cy), nome_time(r["team"]["name"]),
                       font=_fonte_ajustada(d, nome_time(r["team"]["name"]),
                                            COL["J"] - 40 - X_NOME, 25,
                                            minimo=16),
                       fill=_pal()["txt"], anchor="lm")
                gp, gc = r.get("scoresFor", 0), r.get("scoresAgainst", 0)
                valores = {"J": r.get("matches", 0), "V": r.get("wins", 0),
                           "E": r.get("draws", 0), "D": r.get("losses", 0),
                           "GP": gp, "GC": gc, "SG": f"{gp - gc:+d}"}
                for kk, v in valores.items():
                    d.text((COL[kk], cy), str(v), font=f_num,
                           fill=_pal()["txt2"], anchor="rm")
                d.text((COL["PTS"], cy), str(r.get("points", 0)), font=f_pts,
                       fill=_pal()["txt"], anchor="rm")
            # barras de classificação (uma contínua por faixa)
            i = 0
            while i < len(linhas):
                cat = zonas.get(linhas[i]["position"])
                j = i
                while j + 1 < len(linhas) and \
                        zonas.get(linhas[j + 1]["position"]) == cat:
                    j += 1
                if cat is not None:
                    d.rounded_rectangle([MARGEM - 36, y0 + i * LH,
                                         MARGEM - 28, y0 + (j + 1) * LH - 5],
                                        radius=4, fill=meta[cat][0])
                    usadas[cat] = meta[cat]
                i = j + 1
            y = y0 + LH * len(linhas) + GAP

        # legenda
        f_leg = _fonte(21)
        cats = list(usadas.values())
        larguras = [32 + int(d.textlength(rot, font=f_leg)) for _c, rot in cats]
        total = sum(larguras) + 30 * max(len(cats) - 1, 0)
        x = max((W - total) // 2, MARGEM)
        yl = y + 4
        for (cor, rot), w in zip(cats, larguras):
            d.rounded_rectangle([x, yl, x + 20, yl + 20], radius=5, fill=cor)
            d.text((x + 30, yl + 10), rot, font=f_leg, fill=_pal()["txt2"],
                   anchor="lm")
            x += w + 30
        d.text((W // 2, H - 30), "Fonte: Sofascore", font=_fonte(20),
               fill=_pal()["rodape"], anchor="mm")
        nome_arq = "classificacao.png" if len(blocos) == 1 \
            else f"classificacao_{bi}.png"
        img.save(pasta / nome_arq)


def gerar_classificacoes(tabela, pasta, subtitulo):
    """Uma tabela (liga ou fase de liga) ou várias (fase de grupos)."""
    grupos = [g for g in tabela.get("standings", []) if g.get("rows")]
    if not grupos:
        raise RuntimeError("o Sofascore não tem classificação para esta "
                           "competição")
    for velho in pasta.glob("classificacao*.png"):
        try:
            velho.unlink()
        except OSError:
            pass
    if len(grupos) == 1:
        todas = sorted(grupos[0]["rows"], key=lambda r: r["position"])
        if len(todas) <= 24:
            gerar_classificacao({"standings": grupos},
                                pasta / "classificacao.png", subtitulo)
        else:
            # fase de liga grande (ex.: 36 times): várias imagens com a tabela
            # completa e texto grande, em vez de uma imagem comprida
            zonas, meta = zonas_da_tabela(todas)
            partes = -(-len(todas) // 20)
            tam = -(-len(todas) // partes)
            for i in range(partes):
                gerar_classificacao(
                    {"standings": grupos}, pasta / f"classificacao_{i + 1}.png",
                    f"{subtitulo} • {i + 1}/{partes}",
                    linhas=todas[i * tam:(i + 1) * tam], zonas=zonas, meta=meta)
    else:
        gerar_classificacao_grupos(grupos, pasta, subtitulo)


def _arvore_mata_mata(dados):
    """Lê o 'cuptrees' do Sofascore. Retorna [(nome da fase, [confrontos])],
    cada confronto = (lado1, lado2, placar1, placar2), lado = dict."""
    arvores = dados.get("cupTrees") or []
    if not arvores:
        return []

    def conta(a):
        return sum(len(r.get("blocks", [])) for r in a.get("rounds", []))

    arv = max(arvores, key=conta)
    fases = []
    for r in arv.get("rounds", []):
        blocos = []
        for b in r.get("blocks", []):
            partes = b.get("participants") or []

            def lado(i):
                p = partes[i] if i < len(partes) else {}
                t = p.get("team") or {}
                return {"nome": t.get("name") or "", "id": t.get("id"),
                        "venceu": bool(p.get("winner"))}
            blocos.append((lado(0), lado(1), b.get("homeTeamScore"),
                           b.get("awayTeamScore")))
        if blocos:
            nome = r.get("description") or r.get("name") or ""
            fases.append((nome, blocos))
    fases.sort(key=lambda f: -len(f[1]))     # mais confrontos = mais cedo
    return fases


def gerar_chaveamento(dados, caminho, subtitulo):
    """Chave do mata-mata: uma coluna por fase, até a final."""
    from PIL import Image, ImageDraw
    fases = _arvore_mata_mata(dados)
    if not fases:
        raise RuntimeError("o Sofascore não tem chaveamento para esta "
                           "competição")
    COLW, M, TOPO = 400, 60, 215
    ALT_B, GAP = 112, 26
    n_col = len(fases)
    W = max(2 * M + n_col * COLW, 1500)
    max_b = max(len(f[1]) for f in fases)
    area = max_b * (ALT_B + GAP)
    H = TOPO + area + 90
    img = Image.new("RGB", (W, H), _pal()["bg"])
    _textura_fundo(img)
    d = ImageDraw.Draw(img)
    _faixa_topo(d, W)
    xt, xs = _logo_cabecalho(img, M + 10, 40, 40, 96, 144, "classificacao")
    d.text((xt, 40), "Mata-mata", font=_fonte(56, True),
           fill=_pal()["txt"])
    d.text((xs, 112), subtitulo, font=_fonte(28), fill=_pal()["suave"])

    f_nome, f_placar = _fonte(25, True), _fonte(30, True)
    centros = []
    for c, (nome_fase, blocos) in enumerate(fases):
        x0 = M + c * COLW
        larg = COLW - 70
        d.text((x0 + larg // 2, TOPO - 28), traduzir_fase(nome_fase),
               font=_fonte(24, True), fill=_pal()["ouro"], anchor="mm")
        slot = area / len(blocos)
        cs = []
        for j, (l1, l2, p1, p2) in enumerate(blocos):
            cy = int(TOPO + slot * (j + 0.5))
            cs.append(cy)
            y0 = cy - ALT_B // 2
            _caixa(img, [x0, y0, x0 + larg, y0 + ALT_B], _pal()["cartao"],
                   0.92, raio=14)
            for k, (lado, placar) in enumerate(((l1, p1), (l2, p2))):
                yy = y0 + ALT_B // 4 + k * (ALT_B // 2)
                tbd = not lado["nome"]
                perdeu = (not tbd and p1 is not None and p2 is not None
                          and not lado["venceu"]
                          and (l1["venceu"] or l2["venceu"]))
                cor = _pal()["apagado"] if (tbd or perdeu) else _pal()["txt"]
                if not tbd:
                    desenhar_escudo(img, x0 + 34, yy, 34, lado["nome"],
                                    lado["id"])
                nome_exib = nome_time(lado["nome"]) if not tbd else "A definir"
                d.text((x0 + 66, yy), nome_exib,
                       font=_fonte_ajustada(d, nome_exib, larg - 66 - 60, 25,
                                            minimo=15),
                       fill=cor, anchor="lm")
                if placar is not None and str(placar) != "":
                    d.text((x0 + larg - 18, yy), str(placar), font=f_placar,
                           fill=_pal()["ouro"] if lado["venceu"] else cor,
                           anchor="rm")
        centros.append(cs)

    # ligações entre as colunas (só quando cada confronto alimenta um só)
    for c in range(n_col - 1):
        a, b = centros[c], centros[c + 1]
        if len(a) != 2 * len(b):
            continue
        xa = M + c * COLW + (COLW - 70)
        xb = M + (c + 1) * COLW
        xm = (xa + xb) // 2
        for j, cyb in enumerate(b):
            for cya in (a[2 * j], a[2 * j + 1]):
                d.line([xa, cya, xm, cya, xm, cyb, xb, cyb],
                       fill=_pal()["chave"], width=3)
    d.text((W // 2, H - 36), "Fonte: Sofascore", font=_fonte(22),
           fill=_pal()["rodape"], anchor="mm")
    img.save(caminho)


def gerar_todas_imagens(pasta, rodada, debug_dir=None):
    base = f"/unique-tournament/{TOURNAMENT_ID}/season/{SEASON_ID}"
    try:
        tabela = get(f"{base}/standings/total", "classificacao", debug_dir)
        rows = [r for g in tabela.get("standings", []) for r in g.get("rows", [])]
    except Exception as exc:  # noqa
        tabela, rows = None, []
        print(f"  aviso: sem classificação nesta competição ({exc})")
    jogadas = max((r.get("matches", 0) for r in rows), default=0)
    sub = (f"{CFG['nome_curto']} • após a {jogadas}ª rodada" if jogadas
           else CFG["nome_curto"])

    if eh_mata_mata(rodada):
        # fase eliminatória: mostra o chaveamento (se não houver, a tabela)
        try:
            dados = get(f"{base}/cuptrees", "cuptrees", debug_dir)
            gerar_chaveamento(dados, pasta / "chaveamento.png",
                              f"{CFG['nome_curto']} • {rotulo_rodada(rodada)}")
        except Exception as exc:  # noqa
            print(f"  aviso: chaveamento não gerado ({exc}); rode com --debug "
                  f"e envie o arquivo cuptrees.json para conferir")
            if rows:
                gerar_classificacoes(tabela, pasta, sub)
    elif rows:
        gerar_classificacoes(tabela, pasta, sub)
    else:
        print("  aviso: classificação não gerada (sem tabela).")

    for velho_f2 in pasta.glob("f2_stats*.png"):
        try:
            velho_f2.unlink()
        except OSError:
            pass
    if not GERAR_STATS_INDIVIDUAIS:     # apaga as imagens individuais antigas
        for prefixo in ("gols", "assistencias", "defesas", "notas"):
            for velho in pasta.glob(f"{prefixo}*.png"):
                try:
                    velho.unlink()
                except OSError:
                    pass
    # as estatísticas de jogadores nem sempre existem em todas as competições
    try:
        top = get(f"{base}/top-players/overall", "top_players", debug_dir)
    except Exception as exc:  # noqa
        print(f"  aviso: sem estatísticas de jogadores nesta competição ({exc})")
        return

    def tentar(nome, fn):
        try:
            fn()
        except Exception as exc:  # noqa
            print(f"  aviso: imagem '{nome}' não gerada ({exc})")

    paineis = []      # rankings para as estatísticas Formato 2 (2 por imagem)

    def estat(titulo, cab, linhas, arq, curto=None):
        if linhas:
            if GERAR_STATS_INDIVIDUAIS:
                gerar_imagem(titulo, sub, cab, linhas, pasta / arq)
            paineis.append({"titulo": curto or titulo, "metrica": cab,
                            "linhas": linhas})
        else:
            print(f"  aviso: o Sofascore não tem dados de '{titulo}' "
                  f"para esta competição.")

    tentar("artilheiros", lambda: estat(
        "Artilheiros", "GOLS", top_jogadores("goals", top), "gols.png"))
    tentar("assistências", lambda: estat(
        "Assistências", "ASSIST.", top_jogadores("assists", top),
        "assistencias.png"))

    def goleiros_img():
        lista = (_goleiros_do_site(top, base, debug_dir)
                 or melhores_goleiros(_lista_goleiros(base, top, debug_dir),
                                      jogadas))
        if lista:
            if GERAR_STATS_INDIVIDUAIS:
                gerar_imagem("Goleiros: gols sofridos", sub + " • média por jogo",
                             "GOLS/JOGO", lista, pasta / "defesas.png")
            paineis.append({"titulo": "Goleiros", "metrica": "GOLS/JOGO",
                            "linhas": lista})

    tentar("goleiros", goleiros_img)
    tentar("notas", lambda: estat(
        "Melhores notas médias", "NOTA",
        [(n, t, f"{float(v):.2f}", pid, tid)
         for n, t, v, pid, tid in top_jogadores("rating", top)],
        "notas.png", curto="Notas médias"))

    if GERAR_FORMATO2_STATS:
        tentar("estatísticas Formato 2",
               lambda: gerar_stats_f2(paineis, sub, pasta))


# --------------------------------------------------------------------------
def gerar_folha_escudos(destino):
    """Folha de conferência: cada escudo da pasta 'escudos' desenhado como nas
    imagens, com uma linha no ponto central de cada escudo. Para corrigir
    um clube, ajuste seu ID em ajuste_vertical_escudos.json: positivo desce,
    negativo sobe, em proporção à altura renderizada do escudo."""
    global _escudos_so_cache
    from PIL import Image, ImageDraw
    _escudos_so_cache = True
    ids = sorted((a.stem for a in PASTA_ESCUDOS.glob("*.png")),
                 key=lambda t: (not t.isdigit(), int(t) if t.isdigit() else 0, t))
    if not ids:
        print("Nenhum escudo na pasta 'escudos' ainda: gere uma rodada antes.")
        return
    manuais = _ajustes_verticais_escudos()
    cel_w, cel_h, diam, cols = 150, 170, 110, 7
    linhas = (len(ids) + cols - 1) // cols
    folha = Image.new("RGB", (cols * cel_w, linhas * cel_h), (38, 44, 52))
    d = ImageDraw.Draw(folha)
    fonte = _fonte(13, False)
    for k, id_ in enumerate(ids):
        x0, y0 = (k % cols) * cel_w, (k // cols) * cel_h
        cx, cy = x0 + cel_w // 2, y0 + 12 + diam // 2 + 4
        escudo = _carregar_escudo(id_)
        if escudo is None:
            d.text((x0 + 8, y0 + 8), f"{id_}: sem imagem", font=fonte,
                   fill=(255, 120, 120))
            continue
        _colar_escudo(folha, cx, cy, diam, escudo)
        d.line([(x0 + 4, cy), (x0 + cel_w - 4, cy)], fill=(255, 0, 200), width=1)
        ajuste = manuais.get(str(id_), 0.0)
        origem = "manual" if str(id_) in manuais else "padrão"
        d.text((x0 + 6, y0 + cel_h - 22), f"{id_} · {ajuste:+.2f} {origem}",
               font=fonte, fill=(230, 230, 230))
    folha.save(destino)
    print(f"Folha de conferência salva em: {destino}")


def _rodada_da_ultima(saida):
    """Rodada do último tópico gerado (saida/<competição>/ultima.json)."""
    try:
        dados = json.loads((saida / "ultima.json").read_text(encoding="utf-8"))
        return spec_da_chave(dados.get("chave") or f"{dados['rodada']}||")
    except Exception:  # noqa
        return None


def main():
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa
            pass
    ap = argparse.ArgumentParser(description="Gerador do tópico da rodada")
    ap.add_argument("--competicao",
                    help="chave da competição em competicoes.json")
    ap.add_argument("--rodada", type=int)
    ap.add_argument("--rodada-chave",
                    help="rodada/fase escolhida no painel (número|slug|prefixo)")
    ap.add_argument("--sem-imagens", action="store_true")
    ap.add_argument("--sem-site", action="store_true",
                    help="não consulta o futnatv (usa só transmissoes.json)")
    ap.add_argument("--debug", action="store_true",
                    help="salva os JSONs brutos da API")
    ap.add_argument("--listar-nomes", action="store_true",
                    help="lista os nomes de times e estádios da competição "
                         "(usado pelo painel)")
    ap.add_argument("--debug-escudos", action="store_true",
                    help="gera saida/escudos_debug.png mostrando onde cada "
                         "escudo é centralizado (para conferir/ajustar)")
    ap.add_argument("--info-link",
                    help="lê o link de uma competição do Sofascore e imprime "
                         "os dados dela (usado pelo painel)")
    ap.add_argument("--resultados", action="store_true",
                    help="gera só a imagem de resultados da rodada "
                         "(usado pelo painel)")
    # atalho: "--10" equivale a "--rodada 10"
    atalho = None
    argv = []
    for a in sys.argv[1:]:
        m = re.fullmatch(r"--(\d+)", a)
        if m:
            atalho = int(m.group(1))
        else:
            argv.append(a)
    args = ap.parse_args(argv)
    if atalho is not None:
        args.rodada = atalho

    if args.debug_escudos:
        (PASTA_BASE / "saida").mkdir(exist_ok=True)
        gerar_folha_escudos(PASTA_BASE / "saida" / "escudos_debug.png")
        return

    if args.info_link:
        dados = dados_pelo_link(args.info_link)
        print("JSON:" + json.dumps(dados, ensure_ascii=False))
        return

    todas = carregar_competicoes()
    slug = args.competicao or next(iter(todas))
    aplicar_competicao(slug, resolver=True)
    print(f"Competição: {CFG['nome']}")
    if args.listar_nomes:
        print("JSON:" + json.dumps(listar_nomes(), ensure_ascii=False))
        return

    saida = (PASTA_BASE / "saida") / slug
    saida.mkdir(parents=True, exist_ok=True)
    debug_dir = None
    if args.debug:
        debug_dir = saida / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

    if args.rodada_chave:
        rodada = spec_da_chave(args.rodada_chave)
    elif args.rodada is not None:
        rodada = {"round": args.rodada, "name": "", "slug": "", "prefix": ""}
    elif args.resultados and _rodada_da_ultima(saida):
        rodada = _rodada_da_ultima(saida)      # a mesma do último tópico
    else:
        print("Descobrindo a próxima rodada...")
        rodada = descobrir_rodada(debug_dir)
        print(f"Rodada detectada: {rotulo_rodada(rodada)}")

    pasta = saida / pasta_rodada(rodada)
    pasta.mkdir(parents=True, exist_ok=True)

    if args.resultados:
        print(f"Buscando resultados: {rotulo_rodada(rodada)}...")
        caminhos, encerrados, total = atualizar_resultados(
            rodada, pasta, debug_dir)
        print(f"{encerrados} de {total} jogos encerrados.")
        print("JSON:" + json.dumps({
            "pasta": pasta_rodada(rodada), "rotulo": rotulo_rodada(rodada),
            "imagens": [c.name for c in caminhos], "jogos": total,
            "encerrados": encerrados}, ensure_ascii=False))
        return

    print(f"Buscando jogos: {rotulo_rodada(rodada)}...")
    jogos = montar_agenda(rodada, debug_dir, not args.sem_site)
    serial = [{**j, "inicio": j["inicio"].isoformat()} for j in jogos]
    (pasta / "jogos.json").write_text(      # dados puros, sem as edições
        json.dumps(serial, ensure_ascii=False, indent=2), encoding="utf-8")
    jogos = aplicar_edicoes(jogos, carregar_edicoes(pasta))
    texto = formatar_agenda(jogos)
    (pasta / "agenda.txt").write_text(texto, encoding="utf-8")

    titulo = titulo_topico(rodada, jogos)
    (pasta / "titulo.txt").write_text(titulo + "\n", encoding="utf-8")
    (saida / "ultima.json").write_text(
        json.dumps({"rodada": rodada["round"], "pasta": pasta_rodada(rodada),
                    "chave": chave_rodada(rodada)}), encoding="utf-8")

    print(f"\nTÍTULO: {titulo}\n")
    print(texto)
    print(f"Agenda salva em {pasta / 'agenda.txt'}")

    if not args.sem_imagens:
        print("Gerando imagens...")
        try:
            gerar_agendas(jogos, titulo, pasta)
        except Exception as exc:  # noqa
            print(f"AVISO_IMAGENS: imagem da agenda falhou: {exc}")
        try:
            gerar_imagens_destaque(jogos, pasta)
        except Exception as exc:  # noqa
            print(f"AVISO_IMAGENS: imagem do jogo da rodada falhou: {exc}")
        try:
            atualizar_resultados(rodada, pasta, debug_dir)
        except Exception as exc:  # noqa
            print(f"AVISO_IMAGENS: imagem de resultados falhou: {exc}")
        try:
            gerar_todas_imagens(pasta, rodada, debug_dir)
            print(f"Imagens salvas em {pasta}/")
        except Exception as exc:  # a agenda já está salva; não perder tudo
            print(f"AVISO_IMAGENS: não foi possível gerar as imagens: {exc}")


if __name__ == "__main__":
    import atexit
    atexit.register(fechar_browser)
    try:
        main()
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
