"""Gabarito de avaliacao da busca: pergunta -> documentos que deveriam responder.

ESTE E UM GABARITO DE EXEMPLO. As perguntas abaixo apontam para os livros de
UMA base especifica -- a que gerou os numeros do README. Se os seus livros forem
outros, os alvos nao existem e o avaliador vai medir zero.

Para medir a SUA base: troque `PERGUNTAS` por perguntas suas, cada uma com os
pedacos do nome da pasta do documento que deveria responder. Depois rode
`avaliar_dominio.py`. E para isso que o avaliador vem junto.

---

THIS IS AN EXAMPLE GROUND TRUTH. The questions below point at the books of ONE
specific library -- the one that produced the README numbers. With a different
shelf the targets do not exist and the evaluator will score zero.

To measure YOUR library: replace `PERGUNTAS` with your own questions, each with
the fragments of the target document folder name. Then run `avaliar_dominio.py`.

Regras que mantem o gabarito honesto:

- a pergunta e escrita como o dono da base perguntaria, em linguagem natural,
  sem usar o vocabulario exato do livro (senao vira teste de casamento de string);
- o alvo e documento que trata do tema **centralmente**, nao de passagem;
- documento que a curadoria ja marcou como ruim (PDF errado, traducao
  automatica de baixa qualidade) nunca e alvo;
- a versao em ingles existe para o BM25 bilingue competir em pe de igualdade —
  e o que um agente faria antes de consultar.

Cada entrada: (pergunta_pt, pergunta_en, [pedacos do nome da pasta alvo]).
"""

PERGUNTAS = [
    # ---------------------------------------------------------------- vendas
    ("como responder quando o cliente diz que esta muito caro",
     "how to answer when the customer says it is too expensive",
     ["gap-selling", "pricing-creativity"]),
    ("que perguntas fazer numa visita para o cliente perceber o problema sozinho",
     "questions that make the buyer realize the problem themselves in a sales call",
     ["spin-selling", "gap-selling"]),
    ("como manter o funil cheio fazendo contato novo todo dia",
     "keeping the pipeline full with daily new prospecting",
     ["fanatical-prospecting"]),
    ("vale separar quem procura cliente de quem fecha a venda",
     "should we split the role of finding leads from closing deals",
     ["predictable-revenue"]),
    ("o que a pesquisa mostra sobre meta e comissao de vendedor",
     "what research shows about sales quota and commission",
     ["incrivel-ciencia"]),
    ("como descobrir a diferenca entre a situacao atual e a desejada do cliente",
     "finding the gap between the customer current state and desired state",
     ["gap-selling"]),

    # ------------------------------------------------------- copy e persuasao
    ("que tipos de abertura existem para uma carta de vendas",
     "types of lead openings for a sales letter",
     ["great-leads"]),
    ("como escrever um titulo que faz a pessoa continuar lendo",
     "how to write a headline that makes the reader keep going",
     ["copywriter-s-handbook", "copywriting-secrets", "great-leads"]),
    ("por que devolver um favor nos deixa mais propensos a dizer sim",
     "why reciprocity makes people more likely to agree",
     ["influence-manipulation"]),
    ("como montar a narrativa com o cliente no papel de heroi",
     "framing the story with the customer as the hero",
     ["building-a-story-brand"]),
    ("qual a estrutura de um texto de venda do inicio ao pedido",
     "structure of a sales copy from opening to the call to action",
     ["copywriting-secrets", "quickstart-copywriting", "copywriter-s-handbook"]),

    # ------------------------------------------- posicionamento e precificacao
    ("como definir para quem meu produto serve e contra o que ele compete",
     "how to define who the product is for and what it competes against",
     ["obviously-awesome"]),
    ("como cobrar pelo valor entregue em vez de por hora trabalhada",
     "charging for value delivered instead of hourly billing",
     ["pricing-creativity"]),
    ("por que oferecer tres opcoes de preco em vez de uma",
     "why offer three pricing options instead of one",
     ["pricing-creativity"]),
    ("como transformar servico avulso em receita que se repete todo mes",
     "turning one-off service into recurring monthly revenue",
     ["automatic-customer"]),
    ("como escolher um nicho estreito e virar referencia nele",
     "choosing a narrow niche and becoming the expert in it",
     ["business-of-expertise"]),
    ("por que marca cara nao faz promocao nem desconto",
     "why luxury brands never discount",
     ["luxury-strategy"]),
    ("como conversar com cliente sem receber elogio vazio sobre a ideia",
     "talking to customers without getting polite useless praise",
     ["mom-test"]),
    ("como decidir o que planejar antes de comecar um projeto",
     "deciding how much to plan before committing to a project",
     ["inteligencia-pragmatica"]),

    # ------------------------------------------------------- ux e conversao
    ("como usar espacamento e contraste para guiar o olho na tela",
     "using spacing and contrast to guide the eye on screen",
     ["refactoring-ui", "leis-da-psicologia"]),
    ("por que o visitante nao deveria precisar pensar para navegar",
     "why the visitor should not have to think to navigate",
     ["dont-make-me-think"]),
    ("como testar mudancas na pagina para vender mais",
     "testing page changes to increase conversion",
     ["making-websites-win"]),
    ("como manter conversa com usuario toda semana sem virar projeto",
     "keeping weekly customer interviews as a habit",
     ["continuous-discovery"]),
    ("como usar progresso e recompensa para manter a pessoa engajada",
     "using progress and reward to keep people engaged",
     ["actionable-gamification"]),
    ("quanto tempo a pessoa espera antes de desistir de uma tela",
     "how long users wait before abandoning a slow screen",
     ["leis-da-psicologia", "making-websites-win"]),

    # ---------------------------------------------------- engenharia de software
    ("como limitar a complexidade de um metodo para caber na cabeca",
     "limiting method complexity so it fits in your head",
     ["code-that-fits"]),
    ("por que ciclo de retorno curto melhora o software",
     "why short feedback cycles improve software",
     ["modern-software", "code-that-fits"]),
    ("por que nao repetir o mesmo conhecimento em dois lugares do codigo",
     "why not repeat the same knowledge in two places in the code",
     ["pragmatic-programmer"]),
    ("como isolar o banco de dados do resto da aplicacao",
     "isolating the database from the rest of the application",
     ["architecture-patterns"]),
    ("quando escrever o teste antes do codigo compensa",
     "when writing the test before the code pays off",
     ["modern-software", "code-that-fits"]),

    # ------------------------------------------------------ python e dados
    ("como raspar dados de um site e tratar o html",
     "scraping data from a website and parsing the html",
     ["web-scraping"]),
    ("como funcionam compreensao de lista e gerador",
     "how list comprehensions and generators work",
     ["fluent-python", "pense-em-python"]),
    ("como prever uma serie com sazonalidade usando suavizacao",
     "forecasting a seasonal series with exponential smoothing",
     ["forecasting", "forecast-time-series"]),
    ("como equilibrar testar opcao nova e explorar a que ja funciona",
     "balancing exploration and exploitation when testing options",
     ["bandit-algorithms"]),
    ("quando um problema de negocio vale ser resolvido com aprendizado de maquina",
     "when a business problem is worth solving with machine learning",
     ["data-science-for-business"]),
    ("como treinar uma rede neural para classificar imagens",
     "training a neural network to classify images",
     ["aprendizado-profundo"]),

    # ----------------------------------------------------------- ia e llm
    ("quando usar RAG em vez de ajustar o modelo",
     "when to use RAG instead of fine-tuning the model",
     ["building-llms", "ai-engineering"]),
    ("como medir se a resposta do modelo esta boa",
     "how to evaluate whether a model output is good",
     ["ai-engineering", "building-llms"]),
    ("como montar um bot de atendimento sem programar do zero",
     "building a customer service bot without coding from scratch",
     ["snatchbot"]),
    ("o que e mecanismo de atencao num modelo de linguagem",
     "what is the attention mechanism in a language model",
     ["large-language-models", "building-llms"]),

    # -------------------------------------------------- rust, frontend, algoritmo
    ("como a linguagem controla quem e dono da memoria",
     "how the language controls memory ownership and borrowing",
     ["rust-a-linguagem", "zero-to-production"]),
    ("como guardar estado e reagir a mudanca num componente",
     "holding state and reacting to change in a component",
     ["road-to-react"]),
    ("qual a diferenca de custo entre os algoritmos de ordenacao",
     "cost difference between sorting algorithms",
     ["javascript-algorithms"]),

    # ------------------------------------------------------------- marketing
    ("quais sao as leis do marketing de conteudo",
     "the laws of content marketing",
     ["tudo-e-conteu"]),
    ("o que acontece no cerebro na hora de decidir a compra",
     "what happens in the brain at the moment of buying",
     ["neurovendas", "rapido-e-devagar"]),

    # ------------------------------------------------------ treino e nutricao
    ("como treinar por zona de potencia e achar o limiar",
     "training with power zones and finding functional threshold",
     ["power-meter"]),
    ("como dividir a temporada em fases de treino",
     "periodizing the season into training phases",
     ["cyclist"]),
    ("o que comer para aguentar treino longo",
     "what to eat to sustain long endurance training",
     ["endurance-diet"]),

    # --------------------------------------------------- cognicao e decisao
    ("qual a diferenca entre pensar rapido por intuicao e devagar com esforco",
     "difference between fast intuitive thinking and slow effortful thinking",
     ["rapido-e-devagar"]),
    ("como um numero jogado no inicio influencia a estimativa depois",
     "how an initial number anchors a later estimate",
     ["rapido-e-devagar"]),
    ("qual a relacao entre tamanho do grupo social e o cerebro",
     "relation between social group size and the brain",
     ["research-and-perspectives"]),

    # ------------------------------------------------------------ design e arte
    ("como gerar forma visual a partir de regra e algoritmo",
     "generating visual form from rules and algorithms",
     ["generative-algorithms"]),
    ("o que distingue arte de artesanato ou entretenimento",
     "what distinguishes art from craft or entertainment",
     ["principles-of-art"]),
]

# formato usado pelo avaliador: (pt, alvos) e o de-para pt -> en
GABARITO = [(pt, alvos) for pt, _en, alvos in PERGUNTAS]
TRADUCAO = {pt: en for pt, en, _a in PERGUNTAS}
