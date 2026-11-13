# NitroSense for Linux

<!-- A versão em inglês fica em docs/README.en.md: mantenha as duas em sincronia (mesmas seções, tabelas e blocos de código). -->

**Painel de monitoramento e controle para notebooks Acer Nitro no Linux: ventoinhas com curva
automática, saúde do SSD e da bateria, histórico, consumo em watts, detecção de limitação por
calor (*throttling*), alertas e mais.**

Este é um fork de [napejoon/nitrosense-linux](https://github.com/napejoon/nitrosense-linux), um
port do Acer NitroSense 3.01 para Windows. O fork mantém a parte que faz tudo funcionar, um
serviço que roda como root e conversa com o firmware da Acer com os mesmos comandos WMI que o
NitroSense do Windows envia, e troca a janela no estilo Windows por um painel novo. Foi
desenvolvido num **Acer Nitro ANV15-51** (Intel + GeForce RTX 3050) com Linux Mint 22. A interface
está em **português do Brasil**.

> 🇬🇧 [English version](docs/README.en.md) · 🇹🇭 [คู่มือภาษาไทย](docs/README.th.md) (do projeto original, para a janela antiga)

---

## Sumário

- [Destaques](#destaques)
- [Hardware compatível](#hardware-compatível)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Usando o painel](#usando-o-painel)
- [Alertas](#alertas)
- [Proteções](#proteções)
- [Como funciona](#como-funciona)
- [Arquivos e configuração](#arquivos-e-configuração)
- [API do serviço](#api-do-serviço)
- [Referência da interface de firmware](#referência-da-interface-de-firmware)
- [Modelo de segurança](#modelo-de-segurança)
- [Solução de problemas](#solução-de-problemas)
- [Desinstalar](#desinstalar)
- [Desenvolvimento](#desenvolvimento)
- [Origem e créditos](#origem-e-créditos)
- [Limitações](#limitações)
- [Aviso legal](#aviso-legal)
- [Licença](#licença)

---

## Destaques

| Aba | O que mostra ou faz |
|---|---|
| **Início** | Medidores de temperatura da CPU e da GPU com o modelo, o RPM das ventoinhas, o consumo em watts e o uso, o estado do desempenho (normal, ou limitado por calor ou potência) com o clock da CPU, memória, saúde do SSD e da bateria num relance, e um painel lateral para trocar a ventoinha, o modo de energia e os atalhos sem sair da tela. |
| **Cenário** | Planos de energia para tomada e bateria e o controle de ventoinha: **Automático**, **Máx**, **Personalizado** (controles da CPU e da GPU), **Curva** (um gráfico de temperatura por velocidade, arrastável, uma para as duas ventoinhas ou uma para cada, com regras de segurança) e **CoolBoost**. |
| **Discos** | Saúde de NVMe, **SATA e HDD** pelo SMART: desgaste, reserva de células, setores defeituosos, rotação do HDD, horas ligado, dados gravados e lidos, desligamentos inesperados, erros de integridade, temperatura, espaço em uso e conselhos em linguagem simples, com o aviso de quando trocar. |
| **Bateria** | Saúde (capacidade atual contra a original), ciclos, carga, consumo, autonomia, gráficos de histórico e um interruptor para **limitar a carga a cerca de 80%** e a **calibração** da bateria. |
| **Monitoramento** | Gráficos ao vivo dos últimos 12 minutos de temperatura e carga da CPU e da GPU, com watts e clocks. |
| **Processos** | Os programas que mais pesam em CPU, memória e GPU, e o que mantém a GPU dedicada acordada. |
| **Histórico** | De 1 hora a 30 dias: temperaturas, consumo de CPU e GPU, frequência da CPU com os períodos de limitação marcados, carga e consumo da bateria e a tendência de desgaste do SSD. |

Por trás da janela:

- **Um serviço que não dorme.** O `nitrosensed` roda como root, reaplica suas configurações ao
  ligar, ao voltar da suspensão e ao ligar ou desligar o carregador, e grava o histórico o tempo
  todo, **mesmo com a janela fechada**.
- **Alertas com a janela fechada.** O `nitrosense-watch` envia notificações do desktop para
  temperatura alta, ventoinha parada, problemas no SSD ou na bateria e limitação térmica prolongada da CPU ou da GPU.
- **Nunca acorda a GPU dedicada.** O NVML e o `nvidia-smi` só são usados enquanto a GPU já está
  acordada, então o monitoramento não impede que ela economize energia.
- **Ícone na bandeja** (no próprio vigia): muda de cor com o alerta mais grave, mostra os números
  no balão e permite abrir o painel, trocar o modo da ventoinha e ligar o limite de 80% com um clique.
- **A tecla NitroSense** do teclado abre o painel.

---

## Hardware compatível

| Situação | Modelos |
|---|---|
| ✅ Desenvolvido e testado | **Acer Nitro ANV15-51** (Intel, GeForce RTX 3050 6 GB), Linux Mint 22.3, kernel 7.0 |
| ✅ Testado pelo projeto original | **Acer Nitro AN515-44** (Ryzen 4000 + GTX 1650 Ti, BIOS V1.04), Ubuntu 24.04 |
| 🟡 Deve funcionar (mesma interface WMI, `MachineType=1`), não testado | AN515-43, AN515-45, AN515-51s, AN515-54, AN515-55, AN515-56, AN515-57, AN517-41, AN517-51, AN517-52, AN517-53, AN517-54, AN715-41, AN715-51, AN715-52, N9500-A, T9300 |
| ❌ Não suportado (outro NitroSense) | Modelos `MachineType=2` com modos de operação (AN515-46/47/58, AN517-42/43/55, Nitro ANX) e modelos antigos `MachineType=0` |

O que depende do hardware:

| Recurso | Precisa de |
|---|---|
| Controle de ventoinha, sensores, CoolBoost, planos de energia | Os métodos WMI da Acer (`AcerGamingFunction`) e o módulo `acpi_call` |
| Consumo da CPU em watts | Contadores RAPL da Intel em `/sys/class/powercap` (Intel e AMD Zen; o AMD só foi testado com amostras, não em hardware real) |
| Detecção de limitação da CPU | Contadores `thermal_throttle` do kernel e dispositivos de resfriamento térmico (só Intel; em AMD fica o aviso de frequência reduzida pelo sistema) |
| Saúde do disco | **NVMe** (leitura nativa) ou **SATA/SAS/USB**, HDD ou SSD (pelo pacote `smartmontools`) |
| Potência, clock e motivos de redução da GPU | Uma GPU NVIDIA com o driver proprietário (`libnvidia-ml`); numa GPU AMD (`amdgpu`) vêm do sysfs, sem os motivos de redução |
| Uso da GPU por programa | `nvidia-smi` (só NVIDIA) |
| Limite de carga da bateria | A interface WMI de saúde da bateria da Acer (GUID `79772EC5-…`); o interruptor só aparece se o firmware a reportar |
| Iluminação do teclado | O serviço suporta, mas o painel não tem tela de iluminação (veja [Limitações](#limitações)); o firmware do ANV15-51 rejeita o comando de qualquer forma |

As opções de cada modelo (número de ventoinhas, tipo de iluminação, ajustes visíveis) vêm de
`Feature.ini` e `HW_Support.ini`. O repositório traz os do ANV15-51 em `data/models/`; para outro
modelo, o instalador pode pegá-los do pacote do NitroSense para Windows (`Plugs/<modelo>/`).

Num modelo não testado, comece pela sonda de somente leitura, `sudo python3 -I tools/probe.py`, e
confira se as temperaturas e os RPM que ela mostra parecem certos.

---

## Requisitos

- Um notebook Acer Nitro (veja acima) com **Linux Mint 22 / Ubuntu 24.04** ou outra distribuição
  baseada em Debian com **GTK 4.10+** e Python 3.10+.
- Instalados automaticamente: `python3-gi`, `python3-gi-cairo`, `python3-cairo`,
  `gir1.2-gtk-4.0`, `acpi-call-dkms`.
- **Secure Boot**: o `acpi_call` é um módulo de fora do kernel, compilado pelo DKMS. Com Secure Boot
  ligado, o DKMS o assina com a sua chave MOK (*Machine Owner Key*). Se você nunca cadastrou uma, o
  sistema pede uma senha durante a instalação e a opção *Enroll MOK* no próximo boot (tela azul).
- Opcional: `smartmontools` (o instalador tenta instalá-lo), para ler a saúde de discos SATA/HDD; o NVMe
  não precisa dele.
- Opcional: `gir1.2-xapp-1.0` e `gir1.2-gtk-3.0` (o instalador tenta instalá-los), para o ícone na
  bandeja; sem eles o vigia continua enviando as notificações.
- Opcional: o driver da NVIDIA, para as leituras da GPU. Se o `thermald` ou o Intel DPTF estiver
  rodando, os limites dele aparecem na detecção de limitação pelos dispositivos de resfriamento.
- Opcional: o **pacote do NitroSense para Windows** do seu modelo. Ele só serve para os arquivos
  `.ini` de modelos que não estão aqui e para o ícone do app; o painel em si não usa arte da Acer.

---

## Instalação

```bash
git clone https://github.com/reaperdoug-pixel/nitrosense-linux.git
cd nitrosense-linux
sudo ./install.sh                       # arquivos de modelo e ícone que já vêm no repositório
# ou, para pegar os arquivos de modelo e o ícone do seu pacote do NitroSense:
sudo ./install.sh "/caminho/para/Nitro Sense_Acer_3.01.3056_W10x64_A"
```

O que o instalador faz:

1. Confere que a máquina é uma Acer e instala as dependências.
2. Carrega o `acpi_call` e o configura para carregar no boot.
3. Roda uma **sonda de hardware somente de leitura** (só métodos de consulta). Se os valores
   parecerem errados, ele para e não instala mais nada.
4. Copia o programa para `/opt/nitrosense`.
5. Com um pacote: extrai a arte dele para `/usr/share/nitrosense/assets` (nada do pacote é
   executado). Sem pacote: usa o ícone do próprio projeto.
6. Copia os arquivos de modelo (`data/models/<modelo>/` ou `Plugs/<modelo>/` do pacote) para
   `/etc/nitrosense/model/`.
7. Libera o usuário que rodou o `sudo` para falar com o serviço.
8. Instala a entrada no menu, o ícone, o comando `nitrosense` e a inicialização automática do
   **vigia de alertas** (`/etc/xdg/autostart/nitrosense-watch.desktop`).
9. Configura a **tecla NitroSense** (veja [abaixo](#a-tecla-nitrosense)).
10. Habilita e inicia o serviço `nitrosensed`.

Depois abra o **NitroSense** pelo menu de aplicativos ou rode `nitrosense`. O vigia sobe no próximo
login; para iniciá-lo agora, rode `setsid /opt/nitrosense/bin/nitrosense-watch &`.

**Atualizar**: `git pull` e rode o instalador de novo. Suas configurações e o histórico em
`/var/lib/nitrosense` são mantidos. Depois de atualizar, reinicie o vigia (`pkill -f nitrosense-watch`
e inicie-o outra vez), porque o instalador não mexe num que já esteja rodando.

### Instalar pelo pacote `.deb`

Alternativa ao `install.sh`: gere e instale um pacote `.deb`.

```bash
packaging/build-deb.sh
sudo apt install ./dist/nitrosense_*_all.deb
```

O pacote só instala em máquinas Acer, puxa as dependências (inclusive o `acpi-call-dkms`) e ativa o
serviço. Diferenças em relação ao `install.sh`: não extrai a arte do pacote do Windows (usa o ícone
SVG do projeto), não roda o teste de hardware e não registra o atalho da tecla NitroSense; para isso,
logado no desktop, rode `cd /opt/nitrosense && python3 -m nitrosense.shortcut install`. Não misture
os dois métodos: rode `sudo ./uninstall.sh` antes de trocar de um para o outro. Remover com
`sudo apt remove nitrosense` devolve as ventoinhas ao Automático; `sudo apt purge nitrosense` apaga também
a configuração e o histórico.

---

## Usando o painel

Fechar a janela só fecha a interface. O serviço mantém suas configurações e continua gravando. A
última aba usada e a unidade de temperatura (°C/°F) ficam guardadas por usuário.

O visual segue um layout escuro em tons de violeta. O cabeçalho tem a marca, as abas e, à direita, a
fonte de energia com a carga da bateria (por exemplo, "Na tomada · 100%"), a engrenagem das
configurações e os botões de minimizar e fechar. Cada aba abre com um título e uma dica curta.

### Início
À esquerda, os medidores de temperatura da **CPU** e da **GPU**, cada um com o modelo do chip, o uso,
o RPM da ventoinha e o consumo em watts. O anel fica vermelho a partir de 85 °C. Abaixo, um selo de
estado: **Desempenho normal**, **CPU limitada por calor** ou **no limite de potência**, com o clock
da CPU (por exemplo, "CPU 3,3 de 4,6 GHz") e a temperatura em que o processador começa a se
proteger, e uma faixa com a memória em uso, a saúde do SSD, a carga e a saúde da bateria. Quando a
GPU dedicada está suspensa, o medidor mostra "suspensa" em vez de acordá-la. Uma faixa no topo mostra
o [alerta](#alertas) mais grave.

À direita, um painel de controle rápido:

- **Controle de ventoinha**: Auto, Máx, Pers. e Curva. Em Pers. aparecem os controles da CPU e da
  GPU. Mexer num deles já assume o controle manual daquela ventoinha. A curva em si se edita na aba
  Cenário.
- **Modo de energia**: Silencioso, Equilibrado ou Desempenho, para a fonte em uso agora (tomada ou
  bateria).
- **Atalhos**: **CoolBoost** (só no modo Automático), **Bloquear tecla Windows**, **Overdrive da
  tela** e **Limitar carga a 80%**. São os mesmos interruptores de Cenário, Configurações e Bateria,
  e os dois lados se mantêm iguais. Os que o modelo não suporta ficam escondidos.

### Cenário
- **Plano de energia**: planos separados para a tomada e a bateria (Silencioso, Equilibrado,
  Desempenho), trocados automaticamente quando você liga ou desliga o carregador.
- **Controle de ventoinha**: **Automático** (o firmware decide), **Máx**, **Personalizado**
  (controles da CPU e da GPU, de 0 a 100% em passos de 10%, cada um com o seu botão Automático),
  **Curva** e **CoolBoost** (velocidade máxima maior, só no modo Automático).
- **Curva**: arraste os pontos de um gráfico de temperatura por velocidade, ou escolha
  *Silencioso*, *Equilibrado* ou *Desempenho*. A cada 2 s o serviço acompanha a temperatura mais
  alta entre a CPU e a GPU acordada e comanda as duas ventoinhas. Uma linha tracejada mostra a
  temperatura atual. Com **Curvas separadas para cada ventoinha** ligado, a ventoinha da CPU segue a
  temperatura da CPU e a da GPU segue a da GPU (com a GPU suspensa, a da GPU segue a CPU); um seletor
  alterna entre as duas curvas. Veja em [Proteções](#proteções) as regras que a curva não consegue
  desfazer.

### Discos
Para cada NVMe: um selo de saúde (Saudável / Atenção / Crítico), temperatura, desgaste, reserva de
células, horas, dados gravados e lidos, ciclos de energia, desligamentos inesperados, erros de
integridade, um gráfico de temperatura dos últimos 12 minutos, espaço em uso e conselhos. O SMART
exige root, então quem lê é o serviço.

Discos **SATA, SAS e USB** (HDD e SSD) também aparecem, lidos pelo `smartctl` (pacote `smartmontools`).
Para um HDD o cartão mostra a rotação (por exemplo, 5400 RPM, o valor nominal do disco), setores
realocados, pendentes e incorrigíveis, erros de CRC (cabo) e o resultado do último autoteste; para um SSD
SATA, o desgaste quando o disco o informa. O serviço **nunca acorda um HDD em repouso**: ele usa
`smartctl -n standby` e, com o disco dormindo, mantém os dados da última leitura e avisa. A leitura é
feita a cada 2 minutos em segundo plano. Sem o `smartmontools`, o cartão mostra como instalá-lo.

### Bateria
A saúde é a capacidade de carga completa contra a capacidade de projeto, lida de
`/sys/class/power_supply`. Também aparecem ciclos, carga, consumo e autonomia (suavizados no último
minuto), tensão e, se o firmware informar, temperatura. Os gráficos de carga e consumo e a tendência
de saúde usam o histórico. **Limitar a carga a 80%** liga o "modo de saúde" do firmware: a carga
para perto de 80%, o que reduz o desgaste quando o notebook fica na tomada. O serviço reaplica o
limite a cada boot e a cada retorno da suspensão.

**Calibração da bateria**: o firmware carrega a bateria até 100%, descarrega e recarrega uma vez, para o
notebook reaprender a capacidade real (útil quando a saúde parece baixa demais para os ciclos). Leva
várias horas. O botão **Iniciar calibração** pede confirmação e só funciona com o carregador ligado.
O limite de 80% é desligado pelo firmware durante o processo e o serviço o religa no fim. A aba mostra
a fase (carregando, aguardando, descarregando, recarregando) e o tempo decorrido, e **Cancelar
calibração** interrompe a qualquer momento.

### Monitoramento
Gráficos ao vivo dos últimos 12 minutos (uma amostra por segundo) da CPU e da GPU: temperatura
(linha roxa) e carga (área lilás), com a temperatura, a carga, os watts e o clock atuais no
cabeçalho. Se a GPU dedicada estiver desligada, o gráfico avisa em vez de acordá-la.

### Processos
- Os programas que mais pesam em **CPU** (parcela do processador inteiro), **memória** (páginas
  residentes privadas, para que bibliotecas compartilhadas não sejam contadas por processo) e
  **GPU** (memória e uso, via `nvidia-smi pmon`). Programas com muitos processos, como um navegador,
  viram uma linha só.
- **O que mantém a GPU dedicada acordada**: os programas que têm `/dev/nvidia*` aberto, que é o que
  impede a GPU de suspender. Quem fornece isso é o serviço, porque os descritores de arquivo de
  outros usuários exigem root.

### Histórico
Escolha 1 hora, 6 horas, 24 horas, 7 dias ou 30 dias. Gráficos de temperatura da CPU, da GPU e do
SSD, consumo da CPU e da GPU com média, pico e a energia estimada no período, frequência da CPU com
os períodos de limitação térmica marcados em vermelho e um resumo da tendência de desgaste do SSD.
O que é gravado está em [Arquivos e configuração](#arquivos-e-configuração).

### Configurações (engrenagem)
Teclas de aderência (GNOME), trava da tecla Windows/menu (no firmware), unidade de temperatura e as
opções que o modelo suporta: **Usar somente a GPU dedicada**, **Overdrive da tela (LCD)** e
**Apagar luz do teclado após 30 s**. Opções que o firmware não suporta ficam escondidas.

### A tecla NitroSense
A tecla com o logo do NitroSense envia o scancode AT `0xf5`, que o systemd mapeia para
`KEY_PRESENTATION` (keycode 425). O X11 não entrega keycodes acima de 247, então o desktop nunca a
vê. Por isso o instalador adiciona `/etc/udev/hwdb.d/61-nitrosense.hwdb`, que a remapeia para
`prog1` (`XF86Launch1`), e registra um atalho personalizado do GNOME ou do Cinnamon (Linux Mint), *NitroSense*: `XF86Launch1` →
`/opt/nitrosense/bin/nitrosense`. Em outros desktops, associe `XF86Launch1` a esse comando. Para
ver o que qualquer tecla envia: `sudo python3 -I tools/keyprobe.py 20` e aperte a tecla. Para
registrar o atalho do GNOME de novo, como o seu usuário:
`cd /opt/nitrosense && python3 -m nitrosense.shortcut install` (ou `remove` / `status`).

### Ícone na bandeja
O vigia (`nitrosense-watch`) mostra um ícone na bandeja do sistema (XApp StatusIcon: Cinnamon, MATE,
XFCE e outros) que se atualiza a cada 5 s:
- **Cor**: normal (roxo), com um ponto âmbar para **atenção** e vermelho para **crítico**, seguindo o
  [alerta](#alertas) mais grave. Se o serviço ficar indisponível, o ponto âmbar aparece.
- **Balão** (passe o mouse): temperatura, RPM e watts da CPU, temperatura da GPU (ou "GPU suspensa"), SSD,
  bateria com a saúde e o alerta atual.
- **Clique**: abre o NitroSense (ou traz a janela aberta para a frente).
- **Menu** (botão direito): os mesmos números, o submenu **Ventoinha** (Automático / Máx / Curva), o
  interruptor **Limitar a carga a 80%** (bloqueado durante uma calibração) e **Sair (para os alertas
  também)**, que encerra o vigia.

Para iniciar o vigia sem o ícone, use `nitrosense-watch --no-tray` ou a variável de ambiente
`NITROSENSE_NO_TRAY=1`.

---

## Alertas

Os alertas aparecem numa faixa no topo da janela e como notificação do desktop. A notificação sai
quando um alerta surge ou piora. Com o `nitrosense-watch` rodando, ele as envia (também com a janela
fechada), repete a notificação de um alerta crítico que persiste a cada 30 minutos, e a janela fica
quieta, para você nunca receber duplicado.

| Origem | Atenção | Crítico |
|---|---|---|
| Temperatura da CPU | 90 °C | 97 °C |
| Temperatura da GPU | 85 °C | 92 °C |
| Ventoinha | | 0 RPM com a temperatura em 75 °C ou mais |
| CPU limitada por calor | 10 s seguidos ou mais | |
| GPU reduzindo por calor | 10 s seguidos ou mais (informado pelo NVML) | |
| Desgaste do SSD | 80% ou mais | 100% |
| Reserva de células do SSD | abaixo de 50% | no limite do disco ou abaixo |
| HDD/SATA: setores defeituosos | realocados, pendentes ou incorrigíveis: 1 ou mais | 100 ou mais realocados; 10 ou mais pendentes ou incorrigíveis |
| HDD/SATA: SMART | autoteste falhou, atributo que já esteve abaixo do limite, HDD com 5 anos ou mais ligado | SMART reprovado ou atributo abaixo do limite agora |
| Sinalizadores críticos do SSD | falha no backup de memória volátil | reserva, confiabilidade ou somente leitura |
| Erros de integridade do SSD | 1 ou mais | 10 ou mais |
| Temperatura do SSD | a menos de 10 °C do limite de aviso do disco | nesse limite |
| Espaço em disco | 90% cheio | 95% cheio |
| Bateria | | saúde abaixo de 60% ou células a 60 °C ou mais |

A "atenção" da bateria (saúde abaixo de 80%, 1000 ciclos, 50 °C) aparece na aba Bateria, mas não gera
notificação, para não se repetir a cada login.

Para desligar o vigia para um usuário, copie `/etc/xdg/autostart/nitrosense-watch.desktop` para
`~/.config/autostart/` e acrescente a linha `Hidden=true`.

---

## Proteções

O serviço escreve no firmware, então os recursos de risco têm proteções.

**Curva de ventoinha** (regras que a curva não consegue desfazer):
- A velocidade nunca fica abaixo de 20%, e a curva precisa chegar a 100% até 90 °C. O serviço recusa
  outras.
- Em **88 °C (CPU)** ou **82 °C (GPU, quando acordada)** as ventoinhas vão a 100% qualquer que seja
  a curva. Com curvas separadas, essa proteção continua valendo para as duas ventoinhas: se uma das
  temperaturas chegar ao limite, as duas vão a 100%.
- A velocidade sobe na hora, mas só desce depois que o alvo mais baixo se manteve por 8 s, para as
  ventoinhas não oscilarem.
- Se todos os sensores de temperatura falharem por algumas amostras, as ventoinhas voltam ao modo
  automático do firmware, e a curva retoma quando os sensores voltam.
- Quando o serviço para ou reinicia, ele devolve as ventoinhas ao automático. Ele restaura a curva
  depois do boot ou da suspensão. Se o serviço for morto de forma brusca, as ventoinhas ficam na
  última velocidade até ele reiniciar (alguns segundos).
- A curva é coberta por testes unitários contra um firmware simulado. Confira no seu notebook antes
  de confiar nela: escolha **Curva**, observe as temperaturas e os RPM sob carga e volte ao
  **Automático** se algo parecer estranho.

**Limite de carga da bateria**: usa a mesma interface WMI do driver `acer-wmi-battery`. O serviço lê
o estado de volta depois de cada mudança e avisa se o firmware não a aceitou.
O `tools/probe_battery.py` é uma verificação somente de leitura dessa interface.

**Calibração da bateria**: só começa com o carregador ligado e depois de uma confirmação. O firmware
não informa o progresso e nem o driver `acer-wmi-battery` trata o fim do ciclo, então o serviço o
acompanha pelo nível de carga e pelo estado: considera a calibração concluída quando a bateria
chegou a 30% ou menos e voltou a 99% ou mais. Ele a encerra sozinho nesse ponto (e religa o limite de
80%, se estava ligado), a cancela se o firmware a interromper (por exemplo, se o carregador sair da
tomada) e a encerra depois de 16 horas, por segurança. Durante a descarga o sistema pode mostrar avisos
de bateria fraca.

**GPU dedicada**: nada no app a acorda. O NVML e o `nvidia-smi` só são usados enquanto o estado de
runtime PCI está *active*. O alerta de redução por calor com a janela fechada só consulta o NVML
quando a GPU já está acordada **e** a 78 °C ou mais (temperatura do sensor do firmware, que não
envolve a GPU): uma GPU quente está ocupada, então essas leituras não a impedem de suspender.

---

## Como funciona

```
 nitrosense  (GTK 4, seu usuário)        nitrosense-watch  (seu usuário)
        │  socket Unix, linhas JSON             │  mesmo socket
        ▼  /run/nitrosense/nitrosense.sock      ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ nitrosensed (root, Python, systemd)                          │
 │  sensores · ventoinhas e curva · SMART · RAPL · throttling   │
 │  gravador de histórico (a cada 30 s) · estado persistente    │
 └──────────────────────────────────────────────────────────────┘
        │ /proc/acpi/call (acpi_call)            │ /sys, /proc, ioctl do NVMe
        ▼ \_SB.PC00.WMID.WMBH / WMAA / WMBE      ▼
 Controlador embarcado / BIOS (ventoinhas, sensores, bateria)    interfaces do kernel
```

| Módulo | Papel |
|---|---|
| `nitrosense/daemon.py` | O serviço root: servidor de socket com autorização por conexão via `SO_PEERCRED`, estado persistente, reaplicação das configurações no boot, após a suspensão e quando o carregador muda, a curva de ventoinha e as threads de limitação e histórico. |
| `nitrosense/encoders.py` | Uma função pura por método de firmware: transforma um ajuste no valor exato de 64 bits que o NitroSense do Windows envia (testado contra valores do IL descompilado). |
| `nitrosense/wmi.py` | Resolve o caminho ACPI pelo sysfs e chama só os 15 métodos permitidos, cada um com tamanho de entrada fixo. |
| `nitrosense/controller.py` | Sequências de chamadas (modos de ventoinha, iluminação, limite da bateria, …). |
| `nitrosense/fancurve.py` | A curva de ventoinha: validação, interpolação e a máquina de estados de segurança. |
| `nitrosense/disks.py` | SMART do NVMe pelo ioctl de administração, avaliação de saúde (NVMe e ATA) e conselhos. |
| `nitrosense/sata.py` | Discos SATA/SAS/USB pelo `smartctl -j`: descoberta, leitura sem acordar disco em repouso e normalização dos atributos. |
| `nitrosense/battery.py` | Leitura da bateria, avaliação de saúde, tempo restante. |
| `nitrosense/rapl.py` | Consumo da CPU em watts a partir dos contadores de energia RAPL. |
| `nitrosense/throttle.py` | Detecção de limitação da CPU por contadores do kernel e dispositivos de resfriamento. |
| `nitrosense/sysmon.py` | Carga da CPU; carga, temperatura, potência, clock e motivos de redução da NVIDIA pelo NVML, só com a GPU acordada. |
| `nitrosense/procs.py` | CPU e memória por programa a partir de `/proc`, uso da GPU por programa e os processos que seguram `/dev/nvidia*`. |
| `nitrosense/history.py` | O histórico de 30 dias: arquivos JSON-lines por dia, agrupamento e resumos. |
| `nitrosense/alerts.py` | As regras de alerta (uma função pura compartilhada pela janela e pelo vigia). |
| `nitrosense/watcher.py` | O notificador em segundo plano (`nitrosense-watch`), que fala com o serviço de notificações por D-Bus. |
| `nitrosense/tray.py` | O ícone na bandeja do vigia (XApp), com o tooltip, o menu e as regras de ícone por alerta. |
| `nitrosense/power.py` | Planos de energia: governador da CPU, boost e power-profiles-daemon. |
| `nitrosense/gui/window.py`, `widgets.py` | O painel e seus widgets (medidores, gráficos, o editor da curva) e o CSS. |
| `nitrosense/extract.py`, `geometry.py`, `iconmaker.py` | Leem um pacote opcional do Windows (arte, ícone). `gui/controls.py`, `gui/theme.py` e `gui/lighting.py` são auxiliares e o painel de iluminação da janela original. |

### Mapeamento dos planos de energia

O Windows troca esquemas de energia do Windows. O Linux não tem isso, então cada plano vira:

| Plano | Governador da CPU | Boost da CPU | power-profiles-daemon |
|---|---|---|---|
| Silencioso | `schedutil` | desligado | `power-saver` |
| Equilibrado | `schedutil` | ligado | `balanced` |
| Desempenho | `performance` | ligado | `performance` (ou `balanced`, se o sistema não tiver perfil de desempenho) |

---

## Arquivos e configuração

| Caminho | Para que serve |
|---|---|
| `/opt/nitrosense/` | o programa (`bin/nitrosense`, `bin/nitrosensed`, `bin/nitrosense-watch`, o pacote) |
| `/usr/local/bin/nitrosense` | lançador da interface |
| `/etc/nitrosense/model/` | `Feature.ini` e `HW_Support.ini` do seu modelo |
| `/etc/nitrosense/allowed-users` | usuários autorizados a controlar o hardware (um por linha) |
| `/etc/nitrosense/wmi.json` | substituições opcionais dos números dos métodos WMI |
| `/var/lib/nitrosense/state.json` | configurações salvas (modo da ventoinha, curva, limite da bateria, planos de energia, …) |
| `/var/lib/nitrosense/history/history-AAAAMMDD.jsonl` | uma amostra a cada 30 s, 30 dias guardados |
| `/var/lib/nitrosense/history/smart.jsonl`, `battery.jsonl` | contadores de saúde do SSD e da bateria, a cada 6 h, nunca apagados |
| `~/.config/nitrosense/gui.json` | preferências da interface por usuário (unidade, última aba, período do histórico) |
| `/etc/systemd/system/nitrosensed.service` | unidade do serviço |
| `/etc/xdg/autostart/nitrosense-watch.desktop` | inicia o vigia de alertas com a sessão do desktop |
| `/usr/share/icons/hicolor/scalable/apps/nitrosense-tray*.svg` | os três ícones da bandeja (normal, atenção, crítico) |
| `/etc/modules-load.d/nitrosense.conf` | carrega o `acpi_call` no boot |
| `/usr/share/applications/io.github.napejoon.NitroSense.desktop` | entrada no menu (ID do app `io.github.napejoon.NitroSense`) |
| `/etc/udev/hwdb.d/61-nitrosense.hwdb` | tecla NitroSense → `XF86Launch1` |
| configuração do GNOME `custom-keybindings/nitrosense/` | atalho: tecla NitroSense → abrir o NitroSense |

Uma amostra do histórico tem: temperatura da CPU, da GPU e do SSD, RPM das ventoinhas, carga da CPU,
carga e consumo da bateria, potência da CPU, da GPU e da plataforma, frequência média da CPU e a
parcela do intervalo em que ela ficou limitada por calor ou por potência. Leituras que faltam (por
exemplo, a GPU enquanto está dormindo) são omitidas, não zeradas.

Para liberar outro usuário a controlar o hardware:

```bash
echo outrousuario | sudo tee -a /etc/nitrosense/allowed-users
```

---

## API do serviço

O serviço escuta em `/run/nitrosense/nitrosense.sock` e recebe um objeto JSON por linha. Dá para
automatizar, por exemplo em Python:

```python
import sys; sys.path.insert(0, "/opt/nitrosense")
from nitrosense.client import Client
c = Client()
print(c.request("status")["sensors"])   # cpu_temp, gpu_temp, cpu_fan, gpu_fan, cpu_power, igpu_power, sys_power
c.request("set_fan", mode="max")
c.request("set_fan", mode="custom", cpu_percent=60, gpu_percent=40, cpu_auto=False, gpu_auto=False)
c.request("set_fan", mode="auto")
```

| Comando | Argumentos e resposta |
|---|---|
| `status` | nenhum; sensores, `throttle`, `gpu_throttle`, `fan_curve` (estado ao vivo), `state` salvo, estado do firmware (`hw`), estado do carregador |
| `disks` | nenhum; dados SMART por controladora NVMe |
| `history` | `range` 1h/6h/24h/7d/30d; séries agrupadas, resumos, tendências do SSD e da bateria |
| `gpu_holders` | nenhum; programas com `/dev/nvidia*` aberto |
| `set_fan` | `mode` auto/max/custom/curve, opcionais `cpu_auto`, `gpu_auto`, `cpu_percent`, `gpu_percent` |
| `set_fan_curve` | `points`: de 3 a 8 pares `[temperatura, percentual]` (veja [Proteções](#proteções)); opcionais `gpu_points` (a curva da ventoinha da GPU) e `split` (usar uma curva para cada ventoinha) |
| `set_fan_speed` | `fan` cpu/gpu, `percent` 0–100 (só no modo Personalizado) |
| `set_coolboost` | `on` |
| `set_battery_limit` | `on` (só se o firmware suportar; recusado durante uma calibração) |
| `start_battery_calibration` / `stop_battery_calibration` | nenhum; iniciar exige o carregador ligado; o estado vai em `status` → `hw.battery_calibration` |
| `set_keyboard` | `keyboard`: `mode` static/dynamic, `brightness` 1–5, `zones_on` [4 booleanos], `zone_colors` [4 × "#RRGGBB"], `effect` breathing/wave/zoom/shifting/neon, `speed` 1–9, `direction` 1/2, `effect_color` |
| `set_lcd_overdrive` / `set_win_key` / `set_backlight_timeout` | `on` |
| `set_power_plan` | `source` ac/battery, `plan` powersaver/balance/performance |
| `set_gpu_mode` | `discrete_only` (só se suportado; vale depois de reiniciar) |

As respostas são `{"ok": true, ...}` ou `{"ok": false, "error": "..."}`.

---

## Referência da interface de firmware

Classe WMI **AcerGamingFunction**, GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`, ACPI
`<WMID>.WMBH(instância, método, buffer)`. O caminho ACPI é resolvido pelo sysfs: `<WMID>` é
`\_SB.PCI0.WMID` no AN515-44 e `\_SB_.PC00.WMID` no ANV15-51, e os nomes dos objetos (`WMBH`, `WMAA`,
`WMBE`) vêm do `object_id` de cada GUID, então podem mudar de uma BIOS para outra.

| ID | Método | Serve para | Entrada (little-endian) |
|---:|---|---|---|
| 1 | SetGamingProfile | trava da tecla Win, LCD Overdrive | tecla Win: `0x02 \| on<<24`; Overdrive: `0x10 \| on<<48` |
| 3 | GetGamingProfile | ler o LCD Overdrive | `0` → estado no byte 6 |
| 5 | GetGamingSysInfo | sensores | `0x01 \| índice<<8`; índice 1 °C da CPU, 2 RPM da CPU, 6 RPM da GPU, 10 °C da GPU → valor nos bytes 1–2 |
| 6 | SetGamingRgbKb | cor da zona | `zona(1/2/4/8) \| R<<8 \| G<<16 \| B<<24` |
| 14 | SetGamingFanBehavior | modo da ventoinha | `0x9 \| cpu<<16 \| gpu<<22`, por ventoinha 1=auto 2=máx 3=personalizado (Auto `0x410009`, Máx `0x820009`, Personalizado `0xC30009`) |
| 16 | SetGamingFanSpeed | velocidade personalizada | `ventoinha(1=CPU, 4=GPU) \| percentual<<8` |
| 20 | SetGamingKBBacklight | efeito de iluminação | bytes: modo (0 estático, 1 respiração, 2 neon, 3 onda, 4 deslocamento, 5 zoom), velocidade 1–9, brilho 0/25/50/75/100, 0x08 para onda, direção 1 direita / 2 esquerda, R, G, B |
| 22 / 23 | Set/GetGamingMiscSetting | chave de GPU (se suportado) | get `9` → 3 = suportado; set `0x02 \| (1 só dGPU / 2 híbrido)<<8` |
| 7 | GetGamingRgbKb | ler a cor da zona | `zona(1/2/4/8)` → `[status, R, G, B]` |
| 21 | GetGamingKBBacklight | ler o estado da iluminação | → `[status, modo, velocidade, brilho, 0x08, direção, R, G, B]` |

Classe WMI **APGeAction**, GUID `61EF69EA-865C-4BC3-A502-A0DEBA0CB531`, ACPI `<WMID>.WMAA`:

| ID | Método | Serve para | Entrada |
|---:|---|---|---|
| 1 | SetFunction | CoolBoost / tempo da luz do teclado | CoolBoost `0x07 \| on<<16`; tempo `0x02 \| tecla<<8 \| 0x80000 \| brilho<<32 \| (on ? 30<<40 : 0)` |
| 2 | GetFunction | ler os mesmos | CoolBoost `0x207`; luz do teclado `0x01 \| tecla<<8 \| 0x80000` |

Controle de saúde da bateria, GUID `79772EC5-04B1-4BFD-843C-61E7F77B6CC9` (a interface do driver
`acer-wmi-battery`), ACPI `<WMID>.WMBE`:

| ID | Método | Entrada (bytes) | Saída |
|---:|---|---|---|
| 20 | GetBatteryHealth | `[bateria 1, consulta 1, 0, 0]` | byte 0: funções suportadas (1 = modo de saúde, 2 = calibração); byte 3: modo de saúde ligado/desligado; byte 4: calibração ligada/desligada |
| 21 | SetBatteryHealth | `[bateria 1, máscara da função (1 = modo de saúde, 2 = calibração), estado 0/1, 0 …]` (8 bytes) | 4 bytes; o serviço confirma lendo o estado de volta |

Toda saída das duas primeiras classes começa com um byte de status (0 = sucesso); o serviço trata
qualquer outro valor como erro. Na chamada da bateria, o resultado é conferido lendo o estado de
volta.

Notas por modelo:

- **AN515-44** (BIOS V1.04): os IDs 5, 6, 7, 16, 17, 20 e 21 estão implementados no ACPI (`SSDT5`) e
  foram conferidos lá. Os IDs 14, 22 e 23 batem com o driver `acer-wmi` do kernel principal. O ID 1 é
  encaminhado à BIOS por SMI e está confirmado em hardware (trava da tecla Windows). O ID 3 responde
  o Overdrive com `0xFF` no byte 6, que este firmware usa para "não suportado". Teste em hardware:
  12 de 12 verificações de iluminação e ventoinha.
- **ANV15-51**: sensores, modos de ventoinha e o modo de saúde da bateria (leitura e escrita)
  funcionam. O comando de luz do teclado é rejeitado pelo firmware, então o `HW_Support.ini` marca o
  tipo de iluminação como 0. A temperatura da GPU (sensor 10) lê 0 enquanto a GPU dedicada está
  suspensa.
- O `SetGamingLEDBehavior` (máscara de ligar/desligar zona) responde com status 2 na BIOS do
  AN515-44, então uma zona é desligada gravando a cor dela como preta pelo `SetGamingRgbKb`.

Se a sua BIOS for diferente, sobrescreva os números em `/etc/nitrosense/wmi.json`:

```json
{ "methods": { "SetGamingProfile": { "id": 1, "size": 8 } } }
```

O `tools/kbtest.py` percorre todos os modos de iluminação pelo serviço em execução. Para inspecionar
as suas tabelas: `sudo bash tools/collect-acpi.sh` (somente leitura; grava em `tools/acpi-dump/`,
que o git ignora).

---

## Modelo de segurança

- Só o serviço roda como root. A interface e o vigia rodam com o seu usuário.
- O serviço só aceita conexões do root e dos usuários em `/etc/nitrosense/allowed-users`, conferidos
  por conexão com `SO_PEERCRED`. Esses usuários podem ler tudo que o serviço expõe, inclusive os
  nomes dos programas que seguram a GPU aberta.
- As requisições são validadas (tipos, faixas, cores `#RRGGBB`, regras da curva de ventoinha). O
  serviço monta a entrada do firmware por conta própria; os clientes nunca enviam valores WMI
  brutos.
- Só 15 métodos WMI conhecidos podem ser chamados, cada um com tamanho de entrada fixo. Comandos
  desconhecidos são rejeitados. O `smartctl` é chamado sem shell, só para nomes de disco `sd[a-z]`
  vindos do sysfs, com tempo limite.
- O `acpi_call` pode chamar qualquer método ACPI, mas só o root usa o `/proc/acpi/call`.
- O histórico fica em `/var/lib/nitrosense/history/` como arquivos comuns legíveis por todos os
  usuários locais; ele só contém leituras de sensores.
- A unidade do systemd roda com `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true` e
  `NoNewPrivileges=true`.

---

## Solução de problemas

**"NitroSense service is not running"**
```bash
systemctl status nitrosensed
journalctl -u nitrosensed -b
sudo systemctl restart nitrosensed
```

**"Hardware interface unavailable: acpi_call kernel module is not loaded"**
```bash
sudo modprobe acpi_call
dkms status | grep acpi-call
mokutil --sb-state
```
Com Secure Boot ligado, o módulo precisa estar assinado por uma MOK cadastrada. Rode
`sudo dpkg-reconfigure acpi-call-dkms` e reinicie; se a tela da MOK aparecer, escolha *Enroll MOK*.
Depois de uma **atualização do kernel**, o DKMS recompila o módulo sozinho.

**"permission denied"**: acrescente o seu usuário a `/etc/nitrosense/allowed-users`.

**Uma aba diz que o serviço está desatualizado** (histórico, SMART, watts ou `gpu_holders` vazios): o
serviço em execução é mais antigo que a janela. Rode o instalador de novo, ou copie os arquivos e
`sudo systemctl restart nitrosensed`.

**Disco SATA sem dados SMART**: instale o `smartmontools` (`sudo apt install smartmontools`); o serviço tenta
de novo sozinho a cada 2 minutos. Alguns adaptadores USB não repassam o SMART, e o cartão mostra o motivo
que o `smartctl` deu. Um HDD em repouso mostra os dados da última leitura até acordar por conta própria.

**Sem ícone na bandeja**: confira se o painel tem o applet de bandeja (no Cinnamon, *Status XApp*), se
o pacote `gir1.2-xapp-1.0` está instalado e se o vigia foi iniciado sem `--no-tray`. Sem a biblioteca, o
vigia só envia notificações e escreve "tray icon unavailable" na saída.

**Sem notificações do desktop**: confira se o vigia está rodando (`pgrep -f nitrosense-watch`) e se
há um serviço de notificações na sua sessão. A janela só notifica por conta própria quando o vigia
não está rodando.

**A GPU dedicada nunca dorme**: abra a aba **Processos**, que lista os programas que a seguram
aberta. Fechá-los deixa a GPU suspender
(`cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status`).

**Sem consumo em watts**: os contadores RAPL são só do root, então o serviço precisa rodar como root
e estar atualizado; em máquinas AMD o kernel precisa expor o RAPL (versões recentes expõem), e isso não foi testado em hardware real. A potência da GPU só aparece com ela acordada.

**Falta o interruptor do limite de carga**: o firmware não reportou a interface. Rode
`sudo python3 -I tools/probe_battery.py` para ver o que ele responde.

**O Desempenho parece igual ao Equilibrado**: em algumas CPUs o power-profiles-daemon não tem perfil
*performance*. O governador é trocado mesmo assim; confira com
`cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor`.

**A tecla NitroSense não faz nada**
```bash
systemd-hwdb query "evdev:atkbd:$(cat /sys/class/dmi/id/modalias)" | grep f5   # esperado: KEYBOARD_KEY_f5=prog1
cd /opt/nitrosense && python3 -m nitrosense.shortcut status                    # esperado: XF86Launch1 -> ...
```
Se a primeira linha mostrar `presentation`, rode
`sudo systemd-hwdb update && sudo udevadm trigger --sysname-match="event*"`. Se o atalho estiver
faltando, rode `python3 -m nitrosense.shortcut install`.

**Registro de depuração**
```bash
sudo systemctl edit nitrosensed     # acrescente:  [Service]  Environment=NITROSENSE_LOG=DEBUG
sudo systemctl restart nitrosensed
journalctl -u nitrosensed -f        # mostra cada chamada WMI com entrada e saída
```

**Verificação somente de leitura do caminho do hardware**: `sudo python3 -I tools/probe.py`

---

## Desinstalar

```bash
sudo ./uninstall.sh
```

Isso devolve as ventoinhas ao **Automático**, restaura a política de CPU do plano Equilibrado e remove o
serviço, o programa, o vigia de alertas, a configuração, o histórico e o estado salvo. O
`acpi-call-dkms` continua instalado; remova-o com `sudo apt remove acpi-call-dkms` se nada mais o
usar.

Se instalou pelo `.deb`, use `sudo apt purge nitrosense`.

---

## Desenvolvimento

```bash
# testes unitários (156): encoders, serviço contra um firmware simulado, discos, bateria,
# histórico, RAPL, limitação, processos e a curva de ventoinha
python3 -m unittest discover -s tests -v

# rodar o painel a partir do código-fonte contra um notebook simulado (sem root, sem hardware)
python3 tests/fake_hw.py /tmp/ns.sock &
NITROSENSE_SOCKET=/tmp/ns.sock ./bin/nitrosense
```

O `tests/fake_hw.py` simula o firmware (os modos de ventoinha mudam o RPM, as temperaturas variam),
os dados SMART e a potência da CPU. Variáveis para demonstrações: `NITROSENSE_FAKE_HISTORY=1` enche
sete dias de histórico, `NITROSENSE_FAKE_WEAR=<percentual>` define o desgaste do SSD e
`NITROSENSE_FAKE_THROTTLE=1` finge que a CPU está sendo contida e `NITROSENSE_FAKE_SATA=1` finge um HDD e
um SSD SATA.

A janela é um aplicativo de instância única. Para abrir uma segunda cópia ao lado de uma instalada,
inicie-a no seu próprio barramento de sessão e com a sua própria configuração:
`XDG_CONFIG_HOME=$(mktemp -d) dbus-run-session -- python3 -I bin/nitrosense`.

| Variável | Significado |
|---|---|
| `NITROSENSE_SOCKET` | socket do serviço a que a interface e o vigia se conectam |
| `NITROSENSE_MODEL_DIR` | pasta dos `.ini` do modelo (padrão `/etc/nitrosense/model`) |
| `NITROSENSE_ASSETS` | pasta de arte para os auxiliares da janela original (padrão `/usr/share/nitrosense/assets`) |
| `NITROSENSE_LOG` | nível de log do serviço (`DEBUG`, `INFO`, …) |

---

## Origem e créditos

O projeto começou como um port do **NitroSense 3.01.3056** da Acer para Windows, feito por
[napejoon](https://github.com/napejoon/nitrosense-linux) a partir da leitura do próprio aplicativo
do Windows:

1. O instalador do NitroSense contém um `.appxbundle` cujo `.appx` x64 traz `Win32/NitroSense.exe`,
   um aplicativo **WPF** em .NET Framework 4.5; o MSI traz o serviço nativo (`PSSvc`) que fala com
   o WMI.
2. O IL do `NitroSense.exe` revelou cada campo de bits que o app monta, os índices dos sensores e as
   faixas dos controles; textos no binário do serviço ligam cada comando do pipe a um nome de método
   WMI.
3. As tabelas ACPI do notebook foram desmontadas com o `iasl` para confirmar os números dos métodos,
   os tamanhos dos buffers e os índices dos sensores no `WMBH`.

**O que este fork mudou**: a janela no estilo Windows foi substituída pelo painel descrito acima; o
pacote do Windows virou opcional; e o serviço ganhou SMART, histórico, RAPL, limitação, saúde e
limite de carga da bateria, a curva de ventoinha, a lista de processos e o vigia de alertas. A
camada de firmware (`encoders.py`, `wmi.py`, `controller.py`) continua sendo trabalho do projeto
original.

---

## Limitações

- **Idioma da interface**: só português do Brasil.
- **Iluminação do teclado**: o serviço e a API suportam (e o firmware do ANV15-51 rejeita o
  comando), mas o painel não tem tela de iluminação. O painel da janela original continua em
  `nitrosense/gui/lighting.py`, sem uso.
- **Discos**: NVMe e SATA/SAS/USB; discos atrás de RAID por hardware ou de LVM/criptografia mostram a
  saúde do disco físico, mas o espaço em uso só aparece para partições montadas diretamente. O suporte a
  SATA/HDD foi escrito a partir de saídas reais do `smartctl`, mas não foi testado num disco SATA de
  verdade (o notebook de desenvolvimento só tem NVMe).
- **Suporte a AMD**: temperatura da CPU (`k10temp`), watts (RAPL) e a GPU AMD pelo sysfs foram
  implementados e testados só com árvores de sysfs simuladas, não em hardware real. A detecção de
  limitação por calor (contadores `thermal_throttle`) e o uso da GPU por programa continuam só
  para Intel e NVIDIA.
- **Dados da GPU**: só enquanto a GPU dedicada já está acordada; o uso da GPU por programa exige o
  `nvidia-smi`.
- **Potência da plataforma** (`psys`): é gravada mas não é mostrada: no ANV15-51 ela lê menos que o
  pacote da CPU, então não é confiável ali.
- **Não portado** (software só do Windows): os modos de som Waves MaxxAudio / DTS, o botão do NVIDIA
  GeForce Experience e a promoção do Planet9.
- **Planos de energia** viram política de CPU do Linux (veja
  [Mapeamento dos planos de energia](#mapeamento-dos-planos-de-energia)), não esquemas de energia do
  Windows.
- **Teclas de aderência** usam a configuração do GNOME e ficam escondidas em desktops sem ela.
- **Notificações** precisam de um serviço de notificações do desktop; os alertas também aparecem na
  janela.

---

## Aviso legal

Projeto não oficial, sem vínculo com a Acer nem aprovado por ela. "Acer", "Nitro", "NitroSense" e
"CoolBoost" são marcas da Acer Inc. Este repositório não contém código, firmware nem arte da Acer;
o instalador só lê arte de um pacote do NitroSense se você fornecer um, e então o ícone do app vem do
quadro de tecla do próprio NitroSense (`nitrosense/iconmaker.py` acende o N em vermelho como a tecla
retroiluminada). O ícone alternativo `data/icons/io.github.napejoon.NitroSense.svg` é arte original
feita para o projeto original. Alterar ventoinhas e configurações de firmware é por sua conta e
risco.

## Licença

MIT, veja [LICENSE](LICENSE). A licença cobre só o código deste repositório; qualquer arte do
NitroSense que o instalador extraia continua sendo da Acer e não é redistribuída.
