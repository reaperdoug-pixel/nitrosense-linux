# NitroSense for Linux: guia em português

Painel de monitoramento e controle para notebooks **Acer Nitro** no Linux: ventoinhas com
**curva automática**, saúde do SSD e da bateria, histórico, consumo em watts, detecção de
limitação por calor (*throttling*), alertas e mais.

É um fork de [napejoon/nitrosense-linux](https://github.com/napejoon/nitrosense-linux), que é um
port do Acer NitroSense 3.01 para Windows. O serviço que conversa com o firmware da Acer continua
sendo o do projeto original; a janela no estilo Windows foi substituída por um painel novo, em
português, nas cores lilás do Linux Mint. Foi desenvolvido num **Acer Nitro ANV15-51** (Intel +
GeForce RTX 3050) com Linux Mint 22.

O guia completo, com detalhes técnicos, está no [README principal](../README.md) (em inglês).

---

## O que ele faz

| Aba | O que mostra ou faz |
|---|---|
| **Início** | Temperatura e RPM da CPU e da GPU, consumo em watts, carga da GPU, estado do desempenho (normal ou limitado por calor/potência) com o clock da CPU, saúde do SSD e da bateria. |
| **Cenário** | Plano de energia (tomada e bateria) e controle de ventoinha: **Automático**, **Máx**, **Personalizado**, **Curva** (gráfico arrastável) e **CoolBoost**. |
| **Discos** | Saúde do NVMe pelo SMART: desgaste, reserva de células, horas ligado, dados gravados e lidos, desligamentos inesperados, erros, temperatura, espaço em uso e conselhos. |
| **Bateria** | Saúde (capacidade atual contra a original), ciclos, carga, consumo, autonomia, gráficos e o interruptor **Limitar a carga a 80%**. |
| **Monitoramento** | Gráficos ao vivo dos últimos 12 minutos de CPU e GPU. |
| **Processos** | Os programas que mais pesam em CPU, memória e GPU, e o que mantém a GPU dedicada acordada. |
| **Histórico** | De 1 hora a 30 dias: temperaturas, consumo de CPU e GPU, frequência da CPU com os períodos de limitação, carga e consumo da bateria, tendência do SSD. |

Por trás da janela:
- O serviço `nitrosensed` roda como root o tempo todo: reaplica suas configurações ao ligar, ao
  voltar da suspensão e ao ligar ou desligar o carregador, e **grava o histórico mesmo com a janela
  fechada**.
- O `nitrosense-watch` envia **notificações do desktop** para temperatura alta, ventoinha parada,
  problema no SSD ou na bateria e limitação térmica prolongada, também com o app fechado.
- Nada acorda a **GPU dedicada**: ela só é consultada quando já está acordada.
- A **tecla NitroSense** do teclado abre o painel.

---

## Instalação

```bash
git clone https://github.com/reaperdoug-pixel/nitrosense-linux.git
cd nitrosense-linux
sudo ./install.sh
```

O instalador confere que a máquina é Acer, instala as dependências (inclusive o módulo `acpi_call`),
faz uma **sonda de hardware somente de leitura** (se os valores parecerem errados, ele para sem
instalar nada), copia o programa para `/opt/nitrosense`, liga o serviço e cria o atalho no menu, o
comando `nitrosense` e a inicialização automática do vigia de alertas.

Depois abra **NitroSense** pelo menu de aplicativos ou rode `nitrosense`. O vigia de alertas sobe no
próximo login; para iniciar agora: `setsid /opt/nitrosense/bin/nitrosense-watch &`.

Para atualizar: `git pull` e rode o instalador de novo. Suas configurações e o histórico ficam
guardados. Depois de atualizar, reinicie o vigia (`pkill -f nitrosense-watch` e inicie-o outra vez).

**Secure Boot**: o `acpi_call` é um módulo de fora do kernel, compilado pelo DKMS. Com Secure Boot
ligado, ele é assinado com a sua chave MOK. Se você nunca cadastrou uma, o sistema pede uma senha
durante a instalação e, no próximo boot, a opção *Enroll MOK* na tela azul.

---

## Como usar

- **Fechar a janela** só fecha a interface: o serviço continua aplicando suas configurações e
  gravando o histórico.
- **Ventoinha, modo Curva**: arraste os pontos do gráfico (ou use *Silencioso*, *Equilibrado* e
  *Desempenho*). Uma linha tracejada mostra a temperatura atual. Para voltar ao normal, clique em
  **Automático**.
- **Limitar a carga a 80%** (aba Bateria): a carga para perto de 80%, o que reduz o desgaste quando o
  notebook fica ligado na tomada. Desligue o interruptor para voltar a carregar até 100%.
- **Processos**: mostra quem mantém a GPU dedicada acordada. Se ela nunca dorme, comece por aqui.
- **Engrenagem**: teclas de aderência, trava da tecla Windows, unidade de temperatura (°C/°F) e as
  opções que o seu modelo suporta.
- **Tecla NitroSense**: o instalador remapeia a tecla para `XF86Launch1` e cria um atalho do GNOME.
  Em outros desktops, associe `XF86Launch1` ao comando `/opt/nitrosense/bin/nitrosense`.

---

## Alertas

Aparecem numa faixa no topo da janela e como notificação do desktop (o vigia envia, e a janela fica
quieta para não duplicar).

| Origem | Atenção | Crítico |
|---|---|---|
| Temperatura da CPU | 90 °C | 97 °C |
| Temperatura da GPU | 85 °C | 92 °C |
| Ventoinha | | 0 RPM com 75 °C ou mais |
| CPU limitada por calor | 10 s seguidos | |
| Desgaste do SSD | 80% ou mais | 100% |
| Erros de integridade do SSD | 1 ou mais | 10 ou mais |
| Temperatura do SSD | a menos de 10 °C do limite do disco | no limite |
| Espaço no disco | 90% cheio | 95% cheio |
| Bateria | | saúde abaixo de 60% ou 60 °C |

A "atenção" da bateria (saúde abaixo de 80%) aparece só na aba Bateria, sem notificação. Para
desligar o vigia num usuário: copie `/etc/xdg/autostart/nitrosense-watch.desktop` para
`~/.config/autostart/` e acrescente a linha `Hidden=true`.

---

## Segurança

O serviço escreve no firmware, então os recursos de risco têm proteções:

- **Curva de ventoinha**: a velocidade nunca fica abaixo de 20%, e a curva precisa chegar a 100% até
  90 °C. Em **88 °C (CPU)** ou **82 °C (GPU acordada)** as ventoinhas vão a 100% qualquer que seja a
  curva. A velocidade sobe na hora e só desce depois de 8 s com a temperatura mais baixa, para não
  oscilar. Se todos os sensores falharem, as ventoinhas voltam ao automático do firmware, e também
  voltam quando o serviço para.
- **Limite de carga**: depois de cada mudança o serviço lê o estado de volta e avisa se o firmware
  não aceitou.
- A curva foi testada com um firmware simulado. Antes de confiar nela, observe temperaturas e RPM
  sob carga e volte ao **Automático** se algo parecer estranho.

---

## Solução de problemas

- **"NitroSense service is not running"**: `systemctl status nitrosensed`, depois
  `journalctl -u nitrosensed -b` e `sudo systemctl restart nitrosensed`.
- **"acpi_call kernel module is not loaded"**: `sudo modprobe acpi_call`. Com Secure Boot, confira o
  cadastro da chave MOK (`mokutil --sb-state`, `dkms status | grep acpi-call`).
- **"permission denied"**: `echo SEU_USUARIO | sudo tee -a /etc/nitrosense/allowed-users`.
- **Uma aba diz que o serviço está desatualizado** (histórico, SMART, watts vazios): rode o instalador
  de novo ou `sudo systemctl restart nitrosensed`.
- **Sem notificações**: confira se o vigia está rodando (`pgrep -f nitrosense-watch`).
- **A GPU dedicada não dorme**: veja a aba **Processos**; fechar os programas listados deixa a GPU
  suspender (`cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status`).
- **Sem o interruptor de limite de carga**: o firmware não reportou a interface. Rode
  `sudo python3 -I tools/probe_battery.py`.
- **A tecla NitroSense não faz nada**: veja a seção *The NitroSense key* e *Troubleshooting* do
  [README principal](../README.md).

---

## Desinstalar

```bash
sudo ./uninstall.sh
```

As ventoinhas voltam ao Automático, a política de CPU volta ao Equilibrado e o serviço, o programa,
o vigia, a configuração e o histórico são removidos. O `acpi-call-dkms` continua instalado
(`sudo apt remove acpi-call-dkms` se nada mais o usar).

---

## Limitações

- A interface está só em **português do Brasil**.
- A **iluminação do teclado** é suportada pelo serviço e pela API, mas o painel não tem tela de
  iluminação (e o firmware do ANV15-51 rejeita o comando de qualquer forma).
- **Discos**: só NVMe (SATA/HDD exigiriam o `smartmontools`).
- Watts da CPU e detecção de limitação usam interfaces da **Intel**; AMD não foi testado.
- Os dados da **GPU** só aparecem enquanto ela já está acordada.
- Projeto não oficial, sem vínculo com a Acer. Alterar ventoinhas e configurações de firmware é por
  sua conta e risco. Veja o aviso e a licença (MIT) no [README principal](../README.md#disclaimer).
