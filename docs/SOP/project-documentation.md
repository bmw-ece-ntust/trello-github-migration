<h1 align="center">Project Documentation - Guideline</h1>

---

> [!WARNING]
>
> 1. Use this template as the `README.md` of your main research repository.
> 
> 2. The [SOP template of project documentation](https://github.com/bmw-ece-ntust/SOP/blob/master/project-documentation.md) is regularly updated.  
> Please check it regularly.

> [!CAUTION]
> **Confidentiality Notice:**
> Keep this document `private` by default. 
>
> Publish only allowed after the paper of this project is accepted.  
>
> **Note**: Request repository access from the GitHub admin.)

---

> [!NOTE]
> **Documentation Structure:**
>
> - **Installation Guide**: System setup, configuration, and deployment procedures
> - **User Guide**: Operating instructions for the deployed system
> - **Project Documentation**: Technical architecture, use cases, MSC, flowcharts, and class diagrams with links to installation guides

## Purpose

This documentation purposes to describe the main idea of your thesis/paper writing project. Every detail of your project needs to be written in here, thus the co-authors can verify the research results through this document and repositories.

**Documentation Hierarchy:**

```mermaid
graph TD
    PD[Project Documentation]
    
    subgraph "Component A"
        IG-A[Installation Guide A]
        UG-A[User Guide A]
    end

    subgraph "Component B"
        IG-B[Installation Guide B]
        UG-B[User Guide B]
    end

    subgraph "Component C"
        IG-C[Installation Guide C]
        UG-C[User Guide C]
    end

    IG-A --> PD
    IG-B --> PD
    IG-C --> PD
```

## Table of Contents

> [!TIP]
> **Auto-Generate Table of Contents:**
> Use [Markdown All in One](https://marketplace.visualstudio.com/items?itemName=yzhang.markdown-all-in-one#table-of-contents) extension in VS Code for automatic TOC generation.

- [Purpose](#purpose)
- [Table of Contents](#table-of-contents)
- [Introduction](#introduction)
- [Execution Status](#execution-status)
- [Minimum Requirements](#minimum-requirements)
- [System Model](#system-model)
  - [Energy Saving (ES) Use Case: Inputs → Decision → Outputs](#energy-saving-es-use-case-inputs--decision--outputs)
- [System Architecture](#system-architecture)
  - [Software Requirements and Versions](#software-requirements-and-versions)
  - [Components Explanation](#components-explanation)
    - [SMO Layer - O-RAN SC \[L Release\]](#smo-layer---o-ran-sc-l-release)
    - [Near-RT RIC - FlexRIC \[v1.0.0\]](#near-rt-ric---flexric-v100)
    - [Central Unit - OAI \[2024.w40\]](#central-unit---oai-2024w40)
    - [Distributed Unit - OAI \[2024.w40\]](#distributed-unit---oai-2024w40)
    - [Radio Unit - USRP B210](#radio-unit---usrp-b210)
    - [User Equipment](#user-equipment)
- [Use Case Diagram](#use-case-diagram)
- [Message Sequence Chart (MSC)](#message-sequence-chart-msc)
  - [UC2: Handover UEs to Neighbor Cell](#uc2-handover-ues-to-neighbor-cell)
  - [UC3: Shutdown Cell](#uc3-shutdown-cell)
  - [UC4: Activate Cell](#uc4-activate-cell)
- [Flowchart](#flowchart)
  - [UC1: Monitor Traffic Load](#uc1-monitor-traffic-load)
  - [UC2: Handover UEs to Neighbor Cell](#uc2-handover-ues-to-neighbor-cell-1)
  - [UC3: Shutdown Cell](#uc3-shutdown-cell-1)
  - [UC4: Activate Cell](#uc4-activate-cell-1)
- [Class Diagram](#class-diagram)
  - [System Parameters](#system-parameters)
- [References](#references)

## Introduction

> [!NOTE]
> **Guideline:** Define the research background, problem statement, contributions, and challenges. Structure the introduction to be suitable for academic paper publication.
>
> **Required Content:**
>
> 1. **Background**: Describe the problem domain and current state-of-the-art
> 2. **Importance**: Explain why solving this problem matters (technical and practical impact)
> 3. **Contribution**: Present your proposed solution and key innovations
> 4. **Challenges**: Identify implementation challenges and how you address them
>
> **Citation Management:**
>
> - Maintain all references in a `.bib` file for bibliography management
> - Use [Pandoc](https://pandoc.org/) to cite references from the `.bib` file in Markdown
> - The `.bib` file can be directly reused for paper writing in LaTeX

**Example:**

This document presents an O-RAN-based energy saving system for 5G Radio Access Networks (RAN), implementing intelligent multi-cell sleep mechanisms through open interfaces [6] and RAN Intelligent Controllers (RICs) [7].

1. **Background**: 
   - Mobile operators face high energy costs from continuously active base stations during low-traffic periods
   - Traditional RAN architectures lack standardized interfaces [2] for coordinated multi-cell energy optimization

2. **Importance**: 
   - Reduces operational costs by 30-40% through dynamic multi-cell energy management
   - Provides vendor-neutral solutions via O-RAN open interfaces while maintaining QoS

3. **Contribution**: 
   - O-RAN-compliant system leveraging ML-based traffic prediction (Non-RT RIC rApp) and real-time control (Near-RT RIC xApp) for dynamic multi-cell activation/deactivation
   - Novel O1/A1 [5]/E2 [6] interface coordination with intelligent handover algorithms [2] minimizing service disruption

4. **Challenges**: 
   - **UE Handover & QoS**: Zero dropped calls during cell transitions [3] while preventing congestion in remaining active cells
   - **Multi-Cell Coordination**: Accurate traffic prediction and reliable O1/A1/E2 communication for synchronized shutdown/activation decisions

## Execution Status

**Guideline:** Track implementation progress with a status table showing all major development and integration steps. Use status icons (✅ ⏳ ❌) to indicate progress. Include specific dates, outcomes, and error descriptions where applicable.

**Example:**

> [!NOTE]
> **Status Icons:**
> - ✅ Completed successfully
> - ⏳ In progress / Pending
> - ❌ Error / Failed (with explanation)

| Step                                                                  | Status | Timeline   | Execution Status / Notes                                |
| --------------------------------------------------------------------- | ------ | ---------- | ------------------------------------------------------- |
| [Install SMO (O-RAN SC L Release)](#smo-installation)                 | ✅     | 2024-10-15 |                                                         |
| [Install Near-RT RIC (FlexRIC v1.0.0)](#nearrt-ric-install)           | ✅     | 2024-10-16 |                                                         |
| [Install CU (OAI 2024.w40)](#cu-installation)                         | ✅     | 2024-10-17 |                                                         |
| [Install DU (OAI 2024.w40)](#du-installation)                         | ✅     | 2024-10-18 |                                                         |
| [Install RU (USRP B210)](#ru-installation)                            | ✅     | 2024-10-19 |                                                         |
| [Integrate SMO with Near-RT RIC (A1 Interface)](#smo-ric-integration) | ✅     | 2024-10-20 |                                                         |
| [Integrate Near-RT RIC with CU (E2 Interface)](#ric-cu-integration)   | ✅     | 2024-10-20 |                                                         |
| [Integrate Near-RT RIC with DU (E2 Interface)](#ric-du-integration)   | ✅     | 2024-10-21 |                                                         |
| [Integrate CU with DU (F1 Interface)](#cu-du-integration)             | ✅     | 2024-10-21 |                                                         |
| [Integrate DU with RU (eCPRI Interface)](#du-ru-integration)          | ✅     | 2024-10-21 |                                                         |
| [Configure O1 Interface (DU to SMO)](#o1-configuration)               | ✅     | 2024-10-21 |                                                         |
| [Develop Energy Saving rApp](#es-rapp-development)                    | ✅     | 2024-10-22 |                                                         |
| [Develop Energy Saving xApp](#es-xapp-development)                    | ✅     | 2024-10-22 |                                                         |
| [Develop Handover (HO) xApp](#ho-xapp-development)                    | ✅     | 2024-10-23 |                                                         |
| [Test Handover xApp Functionality](#ho-xapp-testing)                  | ✅     | 2024-10-23 |                                                         |
| [Test Cell Shutdown Procedure](#cell-shutdown-testing)                | ✅     | 2024-10-24 |                                                         |
| [Test Cell Wake-up Procedure](#cell-wakeup-testing)                   | ⏳      | 2024-10-25 | Blocked: waiting for cell shutdown tests to complete    |
| [End-to-End Energy Saving Test](#e2e-testing)                         | ❌     | 2024-10-26 | Failed: RU failed to reactivate, investigating RF issue |
| Performance Benchmarking                                              |        | 2024-10-28 |                                                         |
| Documentation and Reporting                                           |        | 2024-10-30 |                                                         |

## Minimum Requirements

> [!NOTE]
> **Guideline:** Specify the minimum hardware and software requirements needed to deploy and run the project. Include CPU, GPU, memory, storage, and network requirements.
>
> **Required Content:**
>
> 1. **Hardware Requirements**: CPU, GPU, RAM, storage, network adapters
> 2. **Software Requirements**: OS, kernel version, runtime dependencies, tools
> 3. **Component-Specific Requirements**: List requirements for each major component (SMO, RIC, DU, RU, etc.)
> 4. **Version Specifications**: Include exact versions for reproducibility

**Example:**

| Component       | Requirement                  |
|-----------------|------------------------------|
| CPU             | 2 GHz dual-core processor    |
| GPU             | NVIDIA GTX 1060 or equivalent|
| Memory (RAM)    | 4 GB RAM                     |
| Storage         | 20 GB available disk space   |
| Network         | 100 Mbps Ethernet connection |

## System Model

> [!NOTE]
> **Guideline:** Define the inputs and outputs of the system, including data formats, protocols, and interfaces used for communication between components.
>
> Describe how data flows through the system from input to output.

### Energy Saving (ES) Use Case: Inputs → Decision → Outputs

```mermaid
flowchart LR
    %% ==================================================
    %% Simple system model for Energy Saving (ES) use case
    %% Focus: inputs/outputs and end-to-end data flow
    %% ==================================================

    subgraph RAN["RAN (gNB)"]
        direction TB
        CU["CU (OAI)"]
        DU["DU (OAI)"]
        RU["RU"]
        UE["UE"]
        CU --- DU --- RU --- UE
    end

    subgraph SMO["SMO (OSC L)"]
        direction TB
        VES["VES Collector\n(O1 event ingestion)"]
        BUS["Kafka / Metrics Store\n(event bus + time-series)"]
        ESrApp["ES rApp (Non-RT RIC)\n(policy / analytics)"]
    end

    subgraph NearRT["Near-RT RIC (OSC L)"]
        direction TB
        E2Term["E2 Termination"]
        ESxApp["ES xApp\n(real-time controller)"]
    end

    %% Inputs extracted from gNB to SMO (O1)
    DU -->|"O1: VES events\ncellStatusChange, timestamp"| VES
    CU -->|"O1: VES events\ncellStatusChange, timestamp"| VES
    VES -->|"Normalized events"| BUS
    BUS -->|"Historical time-series\n(DRB.PrbUtilDL, DRB.PrbUtilUL,\nDRB.UEThpDL, DRB.UEThpUL,\nRRC.ConnectedUE)"| ESrApp

    %% Policy output from Non-RT RIC to Near-RT RIC (A1)
    ESrApp -->|"A1 policy inputs\nprbThresholdLow, prbThresholdHigh,\ndurationThresholdSec"| ESxApp

    %% Near-real-time monitoring input (E2 KPM)
    DU -->|"E2 KPM inputs\nDRB.PrbUtilDL, DRB.PrbUtilUL,\nDRB.UEThpDL, DRB.UEThpUL,\nRRC.ConnectedUE"| E2Term
    E2Term -->|"KPM report"| ESxApp

    %% Decision + actuation outputs (E2 RC)
    ESxApp -->|"E2 RC outputs\nhandoverCmd, targetCellId,\ncellActivationCmd"| E2Term
    E2Term -->|"E2 control"| DU
    E2Term -->|"E2 control"| CU

    %% Observable outputs back to SMO (O1)
    ESxApp -->|"O1 VES events\ncellStatusChange, energySavingEstimate,\ntimestamp"| VES
```



## System Architecture

> [!NOTE]
>
> 1. Use Mermaid diagrams in this note for **AI readability purposes**.
>
> 2. For publication, put the image components **in the slide directly**. Copy-paste the image for other usages when needed.

> [!WARNING]
>
> **Draw.io Files Management:**
>
> If you create system architecture diagrams using draw.io:
>
> 1. Attach the link of the `.drawio` file in this note & any relevant documentation.
> 2. Store the raw `.drawio` files in the `./docs/drawio` folder of the GitHub repository
> 3. Export diagrams as PNG/SVG and embed them in the documentation
> 4. Keep `draw.io` files versioned for easy updates and maintenance
> 5. Use consistent naming: `<project-name>.drawio`

---
> [!NOTE]
> **Guideline:** Draw the end-to-end system architecture using Mermaid diagrams. For each component, provide:
>
> - A **brief component name** with version
> - A **paragraph explanation** of its functionality
> - **Hyperlinks** to corresponding installation guides (use placeholder links)
>
> This format enables easy adaptation into academic paper publications.

**Example:**

```mermaid
graph TB
    %% SMO Layer (Top)
    subgraph SMO["OSC [L] - SMO"]
        direction LR

        subgraph SMO-O1["O1 Agent"]
            direction TB
            VES[VES Collector<br/>Port: 8080]
            NETCONF[NETCONF Server<br/>Port: 830]
        end
        TEIV[TEIV<br/>Port: 8081]
        Grafana[Grafana<br/>Port: 3000]
        
        subgraph Non-RT_RIC["Non-RT RIC"]
            ESrAPP[ES rApp<br/>Port: 9090]
            PMrAPP[PM rApp<br/>Port: 9091]
        end

        SMO-O1 ~~~ TEIV ~~~ Grafana ~~~ Non-RT_RIC
    end
    
    %% Near-RT RIC Layer
    subgraph NearRT_RIC["OSC [L] - Near-RT RIC"]
        HOxAPP[HO xApp<br/>Port: 8080]
        E2Term[E2 Termination<br/>Port: 36421]
        RIC[Near-RT RIC Platform<br/>10.10.4.10]

        HOxAPP ~~~ E2Term
    end
    
    %% CU Layer
    CU["OAI [2024.w40] - CU"]
    
    %% DU Layer
    subgraph DU["OAI [2024.w40] - DU"]
        subgraph DU-O1["O1 Agent"]
            VESAgentDU[VES Agent]
            NETCONFClientDU[NETCONF Client]
        end

        subgraph DU-E2["E2 Agent"]
            E2AP[E2AP]
            E2SM[E2SM]
        end

        DU-O1 ~~~ DU-E2
    end
    
    FHGW[Fronthaul Gateway]

    %% RU Layer
    RU[JURA RU]
    
    %% Connections
    SMO --- |O1| DU
    SMO --- |O1| CU
    SMO --- |A1| NearRT_RIC

    NearRT_RIC --- |E2| CU
    NearRT_RIC --- |E2| DU

    CU --- |F1| DU
    CU --- 5GC[Open5GS] --- Internet
    DU --- FHGW --- RU --- UE

    
    %% Styling
    classDef smo fill:#e1bee7,stroke:#7b1fa2,stroke-width:3px,color:#000
    classDef nonrt fill:#c8e6c9,stroke:#388e3c,stroke-width:2px,color:#000
    classDef ric fill:#fff9c4,stroke:#f57f17,stroke-width:3px,color:#000
    classDef cu fill:#ffcc80,stroke:#e65100,stroke-width:3px,color:#000
    classDef du fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#000
    classDef ru fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#000
    classDef ue fill:#bbdefb,stroke:#1565c0,stroke-width:3px,color:#000
    
    class VES,NETCONF,TEIV,Grafana smo
    class ESrAPP,PMrAPP nonrt
    class RIC,HOxAPP,E2Term ric
    class CU cu
    class VESAgentDU,NETCONFClientDU,E2AP,E2SM du
    class RU ru
    class UE ue
```

### Software Requirements and Versions

| Component        | Implementation    | Version/Release                                                              | Purpose                              |
| ---------------- | ----------------- | ---------------------------------------------------------------------------- | ------------------------------------ |
| SMO              | O-RAN SC          | [L Release (2024.06)](https://wiki.o-ran-sc.org/display/ORAN/L+Release)      | Service Management and Orchestration |
| Non-RT RIC       | O-RAN SC          | [L Release (2024.06)](https://wiki.o-ran-sc.org/display/ORAN/L+Release)      | Non-Real-Time RIC (inside SMO)       |
| VES Collector    | ONAP VES          | [1.12.5](https://github.com/onap/vnfsdk-validation/releases/tag/1.12.5)      | Event collection and normalization   |
| NETCONF Server   | Netopeer2         | [2.1.71](https://github.com/CESNET/netopeer2/releases/tag/v2.1.71)           | Configuration management protocol    |
| TEIV             | O-RAN SC          | [L Release (2024.06)](https://wiki.o-ran-sc.org/display/ORAN/L+Release)      | Topology & Inventory                 |
| Kafka            | Apache Kafka      | [3.6.2](https://archive.apache.org/dist/kafka/3.6.2/)                        | Message broker for event streaming   |
| Grafana          | Grafana           | [10.0.13](https://github.com/grafana/grafana/releases/tag/v10.0.13)          | Monitoring dashboard                 |
| InfluxDB         | InfluxDB          | [2.7.10](https://github.com/influxdata/influxdb/releases/tag/v2.7.10)        | Time-series metrics storage          |
| ES rApp          | Custom Python     | 1.0.0                                                                        | Energy Saving rApp                   |
| PM rApp          | Custom Python     | 1.0.0                                                                        | Performance Monitoring rApp          |
| Near-RT RIC      | O-RAN SC          | [L Release (2024.06)](https://wiki.o-ran-sc.org/display/ORAN/L+Release)      | Real-time RAN Intelligent Controller |
| ES xApp          | Custom C++        | 1.0.0                                                                        | Energy Saving xApp                   |
| HO xApp          | Custom C++        | 1.0.0                                                                        | Handover xApp                        |
| E2 Termination   | O-RAN SC          | [L Release (2024.06)](https://gerrit.o-ran-sc.org/r/gitweb?p=ric-plt/e2.git) | E2 interface termination             |
| CU-CP            | OAI               | [2024.w40](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tags/2024.w40) | Central Unit Control Plane           |
| CU-UP            | OAI               | [2024.w40](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tags/2024.w40) | Central Unit User Plane              |
| DU               | OAI               | [2024.w40](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tags/2024.w40) | Distributed Unit                     |
| E2 Agent (DU)    | FlexRIC           | [v1.0.0](https://github.com/OpenCellular/FlexRIC/releases/tag/v1.0.0)        | E2 agent for DU                      |
| VES Agent (DU)   | ONAP              | [1.12.5](https://github.com/onap/vnfsdk-validation/releases/tag/1.12.5)      | VES agent for O1 interface           |
| NETCONF Client   | Netopeer2         | [2.1.71](https://github.com/CESNET/netopeer2/releases/tag/v2.1.71)           | NETCONF client for O1 interface      |
| RU (SDR)         | USRP B210         | [UHD 4.6.0](https://github.com/EttusResearch/uhd/releases/tag/v4.6.0.0)      | Radio Unit (RF frontend)             |
| UE Module        | Quectel RM500Q-GL | [RM500QGLABR11A06M4G](https://www.quectel.com/product/5g-rm500q-gl)          | User Equipment (5G modem)            |
| Operating System | Ubuntu            | [22.04.5 LTS](https://releases.ubuntu.com/jammy/)                            | Base system platform                 |
| Docker           | Docker Engine     | [24.0.9](https://docs.docker.com/engine/release-notes/24.0/#2409)            | Container runtime                    |
| Kubernetes       | K8s               | [1.28.15](https://github.com/kubernetes/kubernetes/releases/tag/v1.28.15)    | Container orchestration              |

> [!NOTE]
> **O-RAN Version Naming Convention:**
>
> - **O-RAN Alliance Releases**: Named alphabetically (A, B, C, D, E, F, G, H, I, J, K, L, M...)
> - **O-RAN SC (Software Community)**: Follows Alliance releases with specific dates (e.g., L Release = 2024.06)
> - **OAI Releases**: Version numbers (v1.x, v2.x) with weekly tags (e.g., 2024.w40 = week 40 of 2024)
> - **Current Latest**: L Release (June 2024), M Release expected in December 2024

### Components Explanation

#### [SMO Layer - O-RAN SC [L Release]](installation-guide-link)

- **[SMO Platform](smo-installation-link) (10.10.5.10)**: The Service Management and Orchestration platform [7] serves as the top-level management entity in the O-RAN architecture, providing centralized network management, service orchestration, and policy control. Implemented using O-RAN SC L Release, it communicates with lower layers through O1 [4] and A1 [5] interfaces to configure network functions, collect performance metrics, and enforce high-level policies. The SMO enables network slicing, resource allocation optimization, and lifecycle management of RAN components while maintaining a unified view of the entire network topology.

- **[VES Collector](ves-installation-link) (Port 8080)**: The VES (Virtual Event Streaming) Collector receives fault, performance, and event notifications from RAN components through the O1 interface [4]. It normalizes event data from different vendors into a common format, enabling standardized monitoring and analytics across heterogeneous network elements. VES Collector forwards processed events to Kafka message bus for distribution to rApps and external management systems.

- **[NETCONF Server](netconf-installation-link) (Port 830)**: The NETCONF server provides standards-based configuration management for O-RAN network elements through YANG data models. It handles configuration requests from SMO applications, validates changes against YANG schemas, and applies configurations to RAN nodes via O1 interface [4]. The server maintains configuration versioning, supports transaction rollback, and ensures consistent state management across distributed network components.

- **[TEIV](teiv-installation-link) (Port 8081)**: Topology and Inventory (TEIV) service maintains a real-time graph database of network topology, including physical and logical relationships between RAN components. It tracks cell configurations, neighbor relations, hardware inventory, and network connectivity. TEIV provides APIs for rApps to query topology information, enabling intelligent decision-making for optimization algorithms based on current network structure.

- **[Energy Optimization rApp](rapp-installation-link) (Port 9090)**: The Energy Optimization rApp executes on the SMO platform to provide intelligent energy-saving policies based on long-term network analytics and machine learning models. It analyzes historical traffic patterns, cell utilization, and energy consumption data [1] collected over hours or days to generate optimization policies. The rApp trains ML models to predict traffic demand, determines optimal cell sleep schedules, and deploys these policies to the Near-RT RIC through the A1 interface [5] for real-time execution by xApps.

- **[Performance Monitoring rApp](pm-rapp-installation-link) (Port 9091)**: The Performance Monitoring rApp collects and analyzes long-term KPIs [1] from RAN components, detecting performance degradation trends and network anomalies. It aggregates metrics from multiple sources, generates performance reports, triggers alarms for SLA violations, and provides insights for capacity planning. The rApp supports custom analytics workflows and integrates with visualization tools to present network performance trends to operators.

- **[Grafana Dashboard](grafana-installation-link) (Port 3000)**: Grafana provides the web-based visualization and monitoring interface for network operators. It displays real-time and historical metrics including cell throughput, UE connections, resource utilization, and energy consumption across all network layers. Operators can create custom dashboards, configure alert thresholds, analyze performance trends, and correlate events across different network domains through interactive visualizations.

#### [Near-RT RIC - FlexRIC [v1.0.0]](flexric-installation-link)

<Add component explanation>

#### [Central Unit - OAI [2024.w40]](oai-cu-installation-link)

<Add component explanation>

#### [Distributed Unit - OAI [2024.w40]](oai-du-installation-link)

<Add component explanation>

#### [Radio Unit - USRP B210](usrp-installation-link)

<Add component explanation>

#### [User Equipment](ue-installation-link)

<Add component explanation>
| Kubernetes      | 1.18 or higher               |

## Use Case Diagram

> [!NOTE]
> **Guideline:** Define the system features and use cases that fulfill project requirements. Use Mermaid diagrams to illustrate actors, use cases, and their relationships. Each use case will be detailed in the MSC section.
>
> **Required Content:**
>
> 1. **Use Case Diagram**: Mermaid diagram showing actors and their interactions with the system
> 2. **Actor Definitions**: Identify all external entities (users, systems, components)
> 3. **Use Case Definitions**: List all functional capabilities with clear names
> 4. **Relationships**: Show interactions between actors and use cases

**Example:**

```mermaid
graph LR
    %% Actors
    NetworkOperator[Network Operator]
    
    %% Use Cases
    subgraph "Energy Saving System"
        UC1[Monitor<br/>Traffic Load]
        UC2[Handover UEs<br/>to Neighbor Cell]
        UC3[Shutdown<br/>Cell]
        UC4[Activate<br/>Cell]
    end
    
    %% Relationships
    NetworkOperator -->|Configure Policy| UC1
    NetworkOperator -->|View Status| UC1
    
    UC1 -->|Low Traffic| UC2
    UC2 -->|UEs Moved| UC3
    UC1 -->|High Traffic| UC4
    
    %% Styling
    classDef actor fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,color:#000
    classDef usecase fill:#fff9c4,stroke:#f57f17,stroke-width:2px,color:#000
    
    class NetworkOperator actor
    class UC1,UC2,UC3,UC4 usecase
```

## Message Sequence Chart (MSC)

> [!NOTE]
> **Guideline:** Illustrate component interactions for each use case using sequence diagrams. Focus on message flow across system interfaces (O1, A1, E2, F1 for O-RAN). MSC shows **component communication**, while flowcharts show **algorithm logic**.
>
> **Required Content:**
>
> 1. **Sequence Diagrams**: Mermaid diagrams showing message exchanges between components
> 2. **Interface Labels**: Include interface names (O1, A1, E2, F1, eCPRI, Uu)
> 3. **Message Content**: Document message parameters and data structures
> 4. **Timing**: Show order of operations and dependencies
> 5. **Error Scenarios**: Include alternative flows and error handling where relevant

**Example:**

### UC2: Handover UEs to Neighbor Cell

This MSC shows the handover procedure when the Energy Saving xApp decides to move UEs from a low-traffic cell to a neighbor cell before shutdown.

```mermaid
sequenceDiagram
    participant SMO as SMO
    participant NearRTRIC as Near-RT RIC
    participant ESxApp as ES xApp
    participant E2Term as E2 Term
    participant CU as CU
    participant DU as DU
    participant UE as UE
    participant NeighborGNB as Neighbor gNB

    Note over SMO,NeighborGNB: Traffic monitoring detects low load condition
    
    DU->>E2Term: E2 Indication<br/>(KPM: PRB Util 25%, Active UEs: 3)
    E2Term->>ESxApp: KPI Report
    ESxApp->>ESxApp: Analyze: Low Traffic<br/>Decision: Handover Required
    
    Note over SMO,NeighborGNB: Initiate Handover to Neighbor Cell
    
    ESxApp->>E2Term: RIC Control Request<br/>(Action: Handover UEs)
    E2Term->>CU: RIC Control Request
    
    CU->>NeighborGNB: Handover Request<br/>(X2/Xn: UE Context)
    NeighborGNB->>NeighborGNB: Admission Control
    NeighborGNB-->>CU: Handover Ack<br/>(Target Cell Config)
    
    CU->>UE: RRC Reconfiguration<br/>(Handover Command)
    UE->>UE: Sync to Target Cell<br/>RACH Procedure
    UE->>NeighborGNB: RRC Reconfiguration Complete
    NeighborGNB-->>UE: Connection Established
    
    NeighborGNB->>CU: Handover Complete (Xn)
    CU-->>NeighborGNB: UE Context Release
    
    CU->>E2Term: RIC Control Ack<br/>(Handover Success)
    E2Term->>ESxApp: All UEs Handed Over
    
    ESxApp->>NearRTRIC: Status Update<br/>(Cell Ready for Shutdown)
    NearRTRIC->>SMO: O1 Notification<br/>(VES: Handover Complete)
```

### UC3: Shutdown Cell

This MSC shows the cell shutdown procedure after all UEs have been successfully handed over to neighbor cells.

```mermaid
sequenceDiagram
    participant SMO as SMO
    participant NearRTRIC as Near-RT RIC
    participant ESxApp as ES xApp
    participant E2Term as E2 Term
    participant CU as CU
    participant DU as DU
    participant RU as RU

    Note over SMO,RU: All UEs have been handed over to neighbor cells
    
    ESxApp->>ESxApp: Verify: No Active UEs<br/>Decision: Proceed Shutdown
    
    Note over SMO,RU: Initiate Cell Shutdown Command
    
    ESxApp->>E2Term: RIC Control Request<br/>(Action: Deactivate Cell)
    E2Term->>DU: RIC Control Request<br/>(Cell Shutdown)
    
    DU->>DU: Stop Scheduler<br/>Release Radio Resources
    
    DU->>RU: RF Deactivate Command<br/>(Power Down)
    RU->>RU: Shutdown RF Transmission<br/>Enter Sleep Mode
    RU-->>DU: RF Deactivated
    
    DU->>CU: F1 AP: Cell Deactivation<br/>(Notify Cell Unavailable)
    CU-->>DU: Acknowledged
    
    DU->>E2Term: RIC Control Ack<br/>(Cell Shutdown Complete)
    E2Term->>ESxApp: Cell Inactive
    
    ESxApp->>NearRTRIC: Status Update<br/>(Cell: INACTIVE)
    
    Note over SMO,RU: Report to SMO via O1 Interface
    
    NearRTRIC->>SMO: O1 VES Event<br/>(Cell Shutdown Complete)<br/>Timestamp, Cell ID, Power Savings
    SMO->>SMO: Update Dashboard<br/>Log Energy Savings<br/>Estimated: 45W saved
```

### UC4: Activate Cell

This MSC shows the cell activation procedure when traffic load increases and additional capacity is needed.

```mermaid
sequenceDiagram
    participant SMO as SMO
    participant NearRTRIC as Near-RT RIC
    participant ESxApp as ES xApp
    participant E2Term as E2 Term
    participant CU as CU
    participant DU as DU<br/>(INACTIVE)
    participant RU as RU<br/>(SLEEP)

    Note over SMO,RU: High traffic load detected on neighbor cells
    
    ESxApp->>ESxApp: Detect: High Load (PRB > 80%)<br/>Decision: Activate Sleeping Cell
    
    Note over SMO,RU: Initiate Cell Activation Command
    
    ESxApp->>E2Term: RIC Control Request<br/>(Action: Activate Cell)
    E2Term->>DU: RIC Control Request<br/>(Cell Activation)
    
    DU->>RU: RF Activate Command<br/>(Power Up)
    RU->>RU: Initialize RF Chain<br/>Exit Sleep Mode<br/>Carrier Synchronization
    RU-->>DU: RF Ready
    
    DU->>DU: Initialize Scheduler<br/>Allocate Resources<br/>Broadcast System Information
    
    DU->>CU: F1 AP: Cell Activation<br/>(Notify Cell Available)
    CU-->>DU: Acknowledged
    
    DU->>E2Term: RIC Control Ack<br/>(Cell Active, Ready for UEs)
    E2Term->>ESxApp: Cell Activated
    
    ESxApp->>NearRTRIC: Status Update<br/>(Cell: ACTIVE)
    
    Note over SMO,RU: Report to SMO via O1 Interface
    
    NearRTRIC->>SMO: O1 VES Event<br/>(Cell Activation Complete)<br/>Timestamp, Cell ID, Status
    SMO->>SMO: Update Dashboard<br/>Cell Available for Service
    
    Note over SMO,RU: Resume normal traffic monitoring
    
    DU->>E2Term: E2 Indication<br/>(KPM: Cell Active, PRB: 0%)
    E2Term->>ESxApp: Resume Monitoring
```

## Flowchart

> [!NOTE]
> **Guideline:** Define the logic and decision-making algorithms for each use case. Flowcharts illustrate **algorithm logic** (conditional branches, loops, decision criteria), while MSC shows **component interactions**.
>
> **Required Content:**
>
> 1. **Decision Points**: Show conditional branches using diamond shapes
> 2. **Logic Flow**: Include if/else logic and loops with clear conditions
> 3. **Threshold Values**: Document criteria and parameters for decisions
> 4. **Error Handling**: Show alternative paths for failure scenarios
> 5. **Clear Styling**: Use consistent colors and ensure text readability
>
> **Guideline**: [Introduction of flowchart](https://www.geeksforgeeks.org/competitive-programming/an-introduction-to-flowcharts/)

**Example:**

### UC1: Monitor Traffic Load

```mermaid
flowchart TD
    Start([Start: System Initialization])
    Init[Initialize E2 Subscription<br/>Set KPM Interval: 100ms]
    Monitor[Wait for E2 Indication<br/>from DU]
    ReceiveKPI[Receive KPI Report<br/>PRB Utilization, Active UEs]
    
    StoreMetrics[Store Metrics in Time Series DB<br/>InfluxDB]
    
    CheckPolicy{Check A1 Policy<br/>Thresholds}
    
    CheckLowTraffic{PRB < 30% AND<br/>Duration > 5 min?}
    CheckHighTraffic{PRB > 80% AND<br/>Duration > 2 min?}
    
    TriggerHandover[Trigger UC2:<br/>Handover UEs]
    TriggerActivation[Trigger UC4:<br/>Activate Cell]
    
    ContinueMonitor[Continue Monitoring]
    UpdateDashboard[Update SMO Dashboard<br/>Grafana Metrics]
    
    Start --> Init
    Init --> Monitor
    Monitor --> ReceiveKPI
    ReceiveKPI --> StoreMetrics
    StoreMetrics --> CheckPolicy
    CheckPolicy --> CheckLowTraffic
    
    CheckLowTraffic -->|Yes| TriggerHandover
    CheckLowTraffic -->|No| CheckHighTraffic
    
    CheckHighTraffic -->|Yes| TriggerActivation
    CheckHighTraffic -->|No| ContinueMonitor
    
    TriggerHandover --> UpdateDashboard
    TriggerActivation --> UpdateDashboard
    ContinueMonitor --> UpdateDashboard
    UpdateDashboard --> Monitor
    
    style Start fill:#e3f2fd,color:#000
    style TriggerHandover fill:#fff9c4,color:#000
    style TriggerActivation fill:#fff9c4,color:#000
    style CheckLowTraffic fill:#ffcdd2,color:#000
    style CheckHighTraffic fill:#ffcdd2,color:#000
```

### UC2: Handover UEs to Neighbor Cell

```mermaid
flowchart TD
    Start([Start: Handover Triggered])
    GetUEList[Get List of Active UEs<br/>from DU via E2]
    
    CheckUEs{Are there<br/>UEs connected?}
    
    SelectNeighbor[Select Target Neighbor Cell<br/>Check X2/Xn Availability]
    
    InitHandover[Send Handover Request<br/>to Target gNB]
    
    CheckAdmission{Admission<br/>Control OK?}
    
    SendHOCommand[Send RRC Reconfiguration<br/>to UE]
    
    WaitUESync[Wait for UE Sync<br/>Timeout: 5 seconds]
    
    CheckSuccess{UE Handover<br/>Complete?}
    
    ReleaseContext[Release UE Context<br/>from Source Cell]
    
    RetryHandover{Retry Count<br/>< 3?}
    
    MoreUEs{More UEs<br/>to handover?}
    
    AllHandoverDone[All UEs Handed Over<br/>Trigger UC3: Shutdown]
    
    HandoverFailed[Handover Failed<br/>Log Error, Keep Cell Active]
    
    NoUEs[No Active UEs<br/>Proceed to Shutdown]
    
    End([End])
    
    Start --> GetUEList
    GetUEList --> CheckUEs
    
    CheckUEs -->|Yes| SelectNeighbor
    CheckUEs -->|No| NoUEs
    
    SelectNeighbor --> InitHandover
    InitHandover --> CheckAdmission
    
    CheckAdmission -->|Yes| SendHOCommand
    CheckAdmission -->|No| RetryHandover
    
    SendHOCommand --> WaitUESync
    WaitUESync --> CheckSuccess
    
    CheckSuccess -->|Yes| ReleaseContext
    CheckSuccess -->|No| RetryHandover
    
    RetryHandover -->|Yes| SelectNeighbor
    RetryHandover -->|No| HandoverFailed
    
    ReleaseContext --> MoreUEs
    MoreUEs -->|Yes| SelectNeighbor
    MoreUEs -->|No| AllHandoverDone
    
    NoUEs --> AllHandoverDone
    AllHandoverDone --> End
    HandoverFailed --> End
    
    style Start fill:#e3f2fd,color:#000
    style End fill:#e3f2fd,color:#000
    style CheckUEs fill:#ffcdd2,color:#000
    style CheckAdmission fill:#ffcdd2,color:#000
    style CheckSuccess fill:#ffcdd2,color:#000
    style AllHandoverDone fill:#c8e6c9,color:#000
    style HandoverFailed fill:#ffcdd2,color:#000
```

### UC3: Shutdown Cell

```mermaid
flowchart TD
    Start([Start: Shutdown Triggered])
    
    VerifyNoUEs{Verify: No<br/>Active UEs?}
    
    SendShutdown[Send RIC Control Request<br/>E2 Interface to DU]
    
    StopScheduler[DU: Stop MAC Scheduler<br/>Release PRBs]
    
    DeactivateRF[DU → RU: RF Deactivate<br/>Power Down Command]
    
    CheckRF{RU Power Down<br/>Successful?}
    
    NotifyCU[Notify CU via F1 AP<br/>Cell Unavailable]
    
    SendVES[Send VES Event to SMO<br/>Cell Shutdown Complete]
    
    CalcSavings[Calculate Energy Savings<br/>Update Dashboard]
    
    UpdateDB[Update Cell Status DB<br/>Status: INACTIVE]
    
    ShutdownFailed[Shutdown Failed<br/>Log Error, Retry]
    
    WaitHandover[Wait for Handover<br/>Go back to UC2]
    
    End([End: Cell Inactive])
    
    Start --> VerifyNoUEs
    
    VerifyNoUEs -->|Yes| SendShutdown
    VerifyNoUEs -->|No| WaitHandover
    
    SendShutdown --> StopScheduler
    StopScheduler --> DeactivateRF
    DeactivateRF --> CheckRF
    
    CheckRF -->|Yes| NotifyCU
    CheckRF -->|No| ShutdownFailed
    
    NotifyCU --> SendVES
    SendVES --> CalcSavings
    CalcSavings --> UpdateDB
    UpdateDB --> End
    
    WaitHandover --> Start
    ShutdownFailed --> End
    
    style Start fill:#e3f2fd,color:#000
    style End fill:#e3f2fd,color:#000
    style VerifyNoUEs fill:#ffcdd2,color:#000
    style CheckRF fill:#ffcdd2,color:#000
    style CalcSavings fill:#c8e6c9,color:#000
```

### UC4: Activate Cell

```mermaid
flowchart TD
    Start([Start: Activation Triggered])
    
    CheckStatus{Cell Status:<br/>INACTIVE?}
    
    SendActivation[Send RIC Control Request<br/>E2 Interface to DU]
    
    PowerUpRU[DU → RU: RF Activate<br/>Power Up Command]
    
    InitRF[RU: Initialize RF Chain<br/>Carrier Sync, Calibration]
    
    CheckRFReady{RF Ready?<br/>Timeout: 10s}
    
    InitScheduler[DU: Initialize Scheduler<br/>Allocate Resources]
    
    BroadcastSIB[DU: Broadcast SIB<br/>System Information]
    
    NotifyCU[Notify CU via F1 AP<br/>Cell Available]
    
    SendVES[Send VES Event to SMO<br/>Cell Activation Complete]
    
    UpdateDB[Update Cell Status DB<br/>Status: ACTIVE]
    
    StartMonitoring[Resume E2 KPM<br/>Monitoring: UC1]
    
    ActivationFailed[Activation Failed<br/>Log Error, Investigate]
    
    AlreadyActive[Cell Already Active<br/>No Action Needed]
    
    End([End: Cell Active])
    
    Start --> CheckStatus
    
    CheckStatus -->|Inactive| SendActivation
    CheckStatus -->|Active| AlreadyActive
    
    SendActivation --> PowerUpRU
    PowerUpRU --> InitRF
    InitRF --> CheckRFReady
    
    CheckRFReady -->|Yes| InitScheduler
    CheckRFReady -->|No| ActivationFailed
    
    InitScheduler --> BroadcastSIB
    BroadcastSIB --> NotifyCU
    NotifyCU --> SendVES
    SendVES --> UpdateDB
    UpdateDB --> StartMonitoring
    
    StartMonitoring --> End
    AlreadyActive --> End
    ActivationFailed --> End
    
    style Start fill:#e3f2fd,color:#000
    style End fill:#e3f2fd,color:#000
    style CheckStatus fill:#ffcdd2,color:#000
    style CheckRFReady fill:#ffcdd2,color:#000
    style StartMonitoring fill:#c8e6c9,color:#000
```

## Class Diagram

Before jumping into programming implementation, we need to define the:

1. Classes of the system
2. Parameters for each class
3. Functions (Methods in Python) for each class

We should follow the [Object-Oriented Programming (OOP)](https://realpython.com/python3-object-oriented-programming/) principles to design the software architecture.

Furthermore, we need to add [adapter pattern design programming](https://refactoring.guru/design-patterns/abstract-factory), since our rApp and xApp might handles multi-vendor for the same RAN components.

> [!NOTE]
> **Guideline:** Define the software architecture using [Object-Oriented Programming (OOP)](https://realpython.com/python3-object-oriented-programming/) principles. Include:
> 1. Classes
> 2. Attributes/Parameters (following 3GPP standards)
> 3. Functions/Methods
> 4. Relationships (inheritance, composition, aggregation)
> 
> Then, specify your parameters references in the [System Parameters](#system-parameters) table, which define where can we find the standards (3GPP/IEEE) references of your parameters.
>
> Furthermore, we need to add [adapter pattern design programming](https://refactoring.guru/design-patterns/abstract-factory), since our rApp and xApp might handles multi-vendor for the same RAN components.
>
> **Required Content:**
>
> 1. **Classes**: Define main classes following OOP design patterns
> 2. **Attributes**: Use 3GPP parameter names (e.g., `DRB.PrbUtilDL`, `RRC.ConnectedUE`)
> 3. **Methods**: Define functions that execute MSC call-flows
> 4. **Relationships**: Show inheritance (is-a), composition (has-a), aggregation, dependencies
> 5. **Access Modifiers**: Use `-` for private, `+` for public, `#` for protected
> 6. **Data Types**: Specify types (String, Integer, Float, List, etc.)
>
> **OOP Principles:**
>
> - **Encapsulation**: Group related data and methods in classes
> - **Abstraction**: Use interfaces or abstract classes where applicable
> - **Inheritance**: Show class hierarchies (e.g., `BaseXApp` → `EnergySavingXApp`)
> - **Polymorphism**: Define overridable methods

### System Parameters

> [!NOTE]
> **Guideline:** Define the input and output parameters used in the system, following 3GPP specifications. These parameters should be reflected in the class diagram attributes.
>
> **Required Content:**
>
> 1. **Input Parameters**: System inputs (e.g., KPIs from E2 interface, A1 policies)
> 2. **Output Parameters**: System outputs (e.g., control decisions, cell status)
> 3. **3GPP Standards**: Reference TS specifications for each parameter with hyperlinks
> 4. **Parameter Table**: Include columns for Category, Parameter, Type, 3GPP Spec, Unit, Description, Range, Source/Destination

**Example:**

| Category               | Parameter              | Type    | Unit       | 3GPP Spec                                                                                      | Description                             |
| ---------------------- | ---------------------- | ------- | ---------- | ---------------------------------------------------------------------------------------------- | --------------------------------------- |
| **E2 KPM Inputs**      | `DRB.PrbUtilDL`        | Float   | %          | [TS 28.552 §5.1.1.12.1](https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/28552-i50.zip) | Downlink PRB utilization                |
|                        | `DRB.PrbUtilUL`        | Float   | %          | [TS 28.552 §5.1.1.12.2](https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/28552-i50.zip) | Uplink PRB utilization                  |
|                        | `DRB.UEThpDL`          | Float   | kbps       | [TS 28.552 §5.1.1.10.1](https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/28552-i50.zip) | DL UE throughput                        |
|                        | `DRB.UEThpUL`          | Float   | kbps       | [TS 28.552 §5.1.1.10.2](https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/28552-i50.zip) | UL UE throughput                        |
|                        | `RRC.ConnectedUE`      | Integer | count      | [TS 28.552 §5.1.1.1.1](https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/28552-i50.zip)  | Number of active UEs                    |
| **E2 RC Outputs**      | `cellActivationCmd`    | Enum    | -          | [TS 38.331 §6.2.2](https://www.3gpp.org/ftp/Specs/archive/38_series/38.331/38331-i40.zip)      | Cell activation command                 |
|                        | `handoverCmd`          | Struct  | -          | [TS 38.300 §9.2.3.2](https://www.3gpp.org/ftp/Specs/archive/38_series/38.300/38300-i00.zip)    | Handover command                        |
|                        | `targetCellId`         | String  | -          | [TS 36.413 §9.1.2.1](https://www.3gpp.org/ftp/Specs/archive/36_series/36.413/36413-i10.zip)    | Target cell identifier                  |
| **A1 Policy Inputs**   | `prbThresholdLow`      | Float   | %          | [O-RAN.WG2.A1AP-v06.00 §8.2](https://specifications.o-ran.org/)                                | Low PRB threshold for cell sleep        |
|                        | `prbThresholdHigh`     | Float   | %          | [O-RAN.WG2.A1AP-v06.00 §8.2](https://specifications.o-ran.org/)                                | High PRB threshold for cell wake        |
|                        | `durationThresholdSec` | Integer | seconds    | [O-RAN.WG2.A1AP-v06.00 §8.2](https://specifications.o-ran.org/)                                | Minimum duration before action          |
| **Radio Measurements** | `RSRP`                 | Integer | dBm        | [TS 36.214 §5.1.1](https://www.3gpp.org/ftp/Specs/archive/36_series/36.214/36214-i40.zip)      | Reference Signal Received Power         |
|                        | `RSRQ`                 | Integer | dB         | [TS 36.214 §5.1.2](https://www.3gpp.org/ftp/Specs/archive/36_series/36.214/36214-i40.zip)      | Reference Signal Received Quality       |
|                        | `SINR`                 | Integer | dB         | [TS 36.214 §5.1.4](https://www.3gpp.org/ftp/Specs/archive/36_series/36.214/36214-i40.zip)      | Signal to Interference plus Noise Ratio |
| **O1 VES Events**      | `cellStatusChange`     | Event   | -          | [TS 28.532 §5.2.6.2](https://www.3gpp.org/ftp/Specs/archive/28_series/28.532/28532-i50.zip)    | Cell state change notification          |
|                        | `energySavingEstimate` | Float   | Watts      | -                                                                                              | Estimated power savings                 |
|                        | `timestamp`            | Long    | Unix epoch | [TS 28.532 §5.1](https://www.3gpp.org/ftp/Specs/archive/28_series/28.532/28532-i50.zip)        | Event timestamp                         |

**Example:**

```mermaid
classDiagram
    %% ========================================
    %% Core System Components (from System Architecture)
    %% ========================================
    
    %% Near-RT RIC - Energy Saving xApp (Main Controller)
    class EnergySavingXApp {
        <<Near-RT RIC xApp>>
        %% E2 KPM Inputs (from System Parameters)
        -float drbPrbUtilDL
        -float drbPrbUtilUL
        -int rrcConnectedUE
        %% A1 Policy Inputs
        -float prbThresholdLow
        -float prbThresholdHigh
        -int durationThresholdSec
        %% Methods (from Use Cases)
        +monitorTrafficLoad() TrafficStatus
        +initiateHandover(cellId: String) boolean
        +shutdownCell(cellId: String) boolean
        +activateCell(cellId: String) boolean
    }
    
    %% Central Unit (CU)
    class CentralUnit {
        <<OAI 2024.w40>>
        -String cuId
        -int rrcConnectedUE
        %% E2 RC Outputs
        +Struct handoverCmd
        +String targetCellId
        +executeHandover(ueId: String, targetCell: String) boolean
        +releaseUEContext(ueId: String) void
    }
    
    %% Distributed Unit (DU)
    class DistributedUnit {
        <<OAI 2024.w40>>
        -String duId
        %% E2 KPM Inputs
        +float drbPrbUtilDL
        +float drbPrbUtilUL
        +int rrcConnectedUE
        %% E2 RC Outputs
        +Enum cellActivationCmd
        +activateCell() boolean
        +deactivateCell() boolean
        +reportKPM() KPMReport
    }
    
    %% User Equipment
    class UserEquipment {
        <<Quectel RM500Q-GL>>
        -String ueId
        %% Radio Measurements
        +int rsrp
        +int rsrq
        +int sinr
        +sendMeasurementReport() MeasurementReport
    }
    
    %% ========================================
    %% Data Classes (from System Parameters)
    %% ========================================
    
    class KPMReport {
        <<E2SM-KPM>>
        +String cellId
        +long timestamp
        +float drbPrbUtilDL
        +float drbPrbUtilUL
        +int rrcConnectedUE
    }
    
    class TrafficStatus {
        +String cellId
        +float avgPrbUtil
        +int activeUEs
        +boolean lowTraffic
        +boolean highTraffic
    }
    
    class MeasurementReport {
        +String ueId
        +int rsrp
        +int rsrq
        +int sinr
    }
    
    %% ========================================
    %% Relationships
    %% ========================================
    
    %% E2 Interface Connections
    EnergySavingXApp "1" -- "1" CentralUnit : E2 Interface
    EnergySavingXApp "1" -- "1" DistributedUnit : E2 Interface
    
    %% F1 Interface
    CentralUnit "1" -- "1" DistributedUnit : F1 Interface
    
    %% Uu Interface
    DistributedUnit "1" -- "*" UserEquipment : Uu Interface
    
    %% Data Flow
    DistributedUnit ..> KPMReport : generates
    EnergySavingXApp ..> KPMReport : processes
    EnergySavingXApp ..> TrafficStatus : analyzes
    UserEquipment ..> MeasurementReport : generates
```

## References

> [!NOTE]
> **Guideline:** Use IEEE citation style for all references. Cite references in the text using numerical format [1], [2], etc., and list them in order of appearance at the end of the document.
>
> **Citation Format:**
>
> - In-text citations: Use square brackets with numbers [1], [2], [3]
> - Multiple citations: [1], [2] or [1]–[3] for ranges
> - References list: Number sequentially in order of first appearance
>
> **For Pandoc Conversion:**
>
> - Create a `references.bib` file with BibTeX entries
> - Use Pandoc with IEEE CSL: `pandoc document.md --bibliography=references.bib --citeproc --csl=ieee.csl -o output.pdf`
> - Download `ieee.csl` from: https://github.com/citation-style-language/styles/blob/master/ieee.csl

**Example References (IEEE Format):**

[1] 3GPP, "Management and orchestration; 5G performance measurements," 3rd Generation Partnership Project (3GPP), Technical Specification TS 28.552 V18.5.0, 2024. [Online]. Available: https://www.3gpp.org/ftp/Specs/archive/28_series/28.552/

[2] 3GPP, "NR; NR and NG-RAN Overall description; Stage-2," 3rd Generation Partnership Project (3GPP), Technical Specification TS 38.300 V18.0.0, 2024. [Online]. Available: https://www.3gpp.org/ftp/Specs/archive/38_series/38.300/

[3] 3GPP, "NR; Radio Resource Control (RRC) protocol specification," 3rd Generation Partnership Project (3GPP), Technical Specification TS 38.331 V18.4.0, 2024. [Online]. Available: https://www.3gpp.org/ftp/Specs/archive/38_series/38.331/

[4] 3GPP, "Management and orchestration; Generic management services," 3rd Generation Partnership Project (3GPP), Technical Specification TS 28.532 V18.5.0, 2024. [Online]. Available: https://www.3gpp.org/ftp/Specs/archive/28_series/28.532/

[5] O-RAN Alliance, "O-RAN.WG2.A1AP-v06.00: O-RAN A1 interface: Application Protocol," O-RAN Alliance, Technical Specification, 2024. [Online]. Available: https://specifications.o-ran.org/

[6] O-RAN Alliance, "O-RAN.WG3.E2AP-v03.01: O-RAN E2 Application Protocol," O-RAN Alliance, Technical Specification, 2024. [Online]. Available: https://specifications.o-ran.org/

[7] O-RAN Software Community, "O-RAN Software Community L Release," 2024. [Online]. Available: https://wiki.o-ran-sc.org/display/ORAN/L+Release. [Accessed: Oct. 24, 2024].

[8] EURECOM, "OpenAirInterface 5G RAN Implementation," Version 2024.w40, 2024. [Online]. Available: https://gitlab.eurecom.fr/oai/openairinterface5g