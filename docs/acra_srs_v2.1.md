# Integrated Manufacturing Execution System (MES)
# Software Requirements Specification — Phase 1–3

**Version:** 2.1
**Date:** March 17, 2026
**Status:** Draft

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Functional Requirements](#2-functional-requirements)
3. [Non-Functional Requirements](#3-non-functional-requirements)
4. [Software Requirements Specification](#4-software-requirements-specification)
5. [Use Cases](#5-use-cases)
6. [UML Diagrams](#6-uml-diagrams)

---

## 1. Problem Statement

### 1.1 The Problem

Small and medium-sized manufacturing enterprises (SMEs) continue to depend on paper-based documentation, disconnected spreadsheets, and manual tracking methods to manage their end-to-end production operations. In the target facility — a small-scale manufacturer operating five production lines that fulfills orders from a parent company — this reliance on manual processes creates a cascade of operational inefficiencies that directly impact productivity, accuracy, and profitability.

**Specifically, the facility faces the following challenges:**

- **Manual data entry from shipping documents:** When trucks deliver raw materials, warehouse staff must manually transcribe information from bills of lading into spreadsheets. This process is slow, error-prone, and creates delays before materials are even recognized in inventory.

- **Lack of real-time inventory visibility:** Without a centralized digital system, there is no reliable way to know current stock levels of raw materials or finished goods at any given moment. Staff rely on periodic physical counts and disconnected spreadsheets that are frequently outdated or inconsistent.

- **Disconnected production tracking:** Work orders from the parent company arrive as spreadsheets and are managed through informal communication. There is no centralized system to create, assign, and track production orders through their lifecycle — from material allocation to manufacturing to completion.

- **Limited lot and batch traceability:** The facility cannot efficiently trace which raw material lots were used in specific production runs, making quality investigations and compliance audits difficult and time-consuming.

- **Inefficient coordination between roles:** Warehouse staff, machine operators, and supervisors lack a shared system for communication. Production status updates and shipping readiness are communicated verbally or through paper notes, leading to delays and miscommunication.

- **No production performance data:** Without digital tracking at the machine level, the facility has no reliable data on production throughput, scrap/waste rates, machine utilization, or time-per-order — making it impossible to identify bottlenecks, reduce waste, or make data-driven operational decisions.

### 1.2 Significance

These challenges are not unique to a single facility. Across the manufacturing sector, SMEs face a technology gap: large enterprises invest in expensive Enterprise Resource Planning (ERP) and Manufacturing Execution Systems (MES) costing hundreds of thousands of dollars, while smaller manufacturers are left to manage operations with tools that were never designed for manufacturing workflows. The result is that SMEs operate below their potential — absorbing preventable costs from errors, delays, and inefficiency — while lacking the data needed to improve.

### 1.3 Scope

This document covers the initial delivery phase of an integrated, web-based Manufacturing Execution System (MES). It encompasses four functional areas:

1. **Receiving and Intake** — OCR-powered scanning of bills of lading to automate material receiving and reduce data entry time by 60–70%.
2. **Inventory Management** — Real-time tracking of raw materials and finished goods with lot/batch traceability and automated stock alerts.
3. **Work Order Management** — Digital creation, assignment, and lifecycle tracking of production orders with material allocation.
4. **Role-Based Access Control** — Differentiated system access for four user roles: Company Admin, Receiving/Shipping Clerk, Production Supervisor, and Machine Operator.

The system will be built using modern, open-source web technologies (React.js, FastAPI, PostgreSQL) with a mobile-responsive interface, ensuring accessibility across desktop and handheld devices used on the factory floor. The project will follow an Agile development methodology, delivering a working prototype with full functionality designed for immediate deployment.

---

## 2. Functional Requirements

### 2.1 Receiving and Intake

| ID | Requirement | Roles |
|----|-------------|-------|
| FR-001 | The system shall allow the Receiving/Shipping Clerk to log incoming material deliveries by entering supplier name, truck/carrier information, delivery date, and material details. | Receiving/Shipping Clerk, Admin |
| FR-002 | The system shall provide OCR scanning capability that extracts data from photographs or scans of bills of lading and auto-populates delivery entry fields. | Receiving/Shipping Clerk, Admin |
| FR-003 | The system shall allow the user to review, edit, and confirm OCR-extracted data before committing a delivery record. | Receiving/Shipping Clerk, Admin |
| FR-004 | The system shall automatically create inventory entries for received materials upon delivery confirmation, including quantity, lot/batch number, material type, and storage location. | System |
| FR-005 | The system shall maintain a searchable log of all receiving records with delivery date, supplier, carrier, bill of lading reference, and materials received. | Receiving/Shipping Clerk, Admin |

### 2.2 Inventory Management

| ID | Requirement | Roles |
|----|-------------|-------|
| FR-006 | The system shall maintain a real-time inventory of all raw materials, including quantity on hand, lot/batch number, material type, and storage location. | All Roles (view varies by role) |
| FR-007 | The system shall maintain a real-time inventory of all finished goods, including quantity on hand, associated work order, lot/batch number, and storage location. | All Roles (view varies by role) |
| FR-008 | The system shall automatically update inventory quantities when materials are received, allocated to work orders, consumed in production, or shipped. | System |
| FR-009 | The system shall provide configurable stock level alerts that notify the Admin when raw material quantities fall below a defined threshold. | Admin |
| FR-010 | The system shall support lot/batch traceability, allowing users to trace which raw material lots were used in specific production runs and which finished goods resulted from those runs. | Admin, Production Supervisor |
| FR-011 | The system shall provide inventory search and filtering by material type, lot/batch number, storage location, and date received. | Admin, Production Supervisor, Receiving/Shipping Clerk |
| FR-012 | The system shall maintain a full audit trail of all inventory transactions (receipts, allocations, consumption, adjustments, shipments) with timestamps and the user who performed the action. | Admin |

### 2.3 Work Order Management

| ID | Requirement | Roles |
|----|-------------|-------|
| FR-013 | The system shall allow the Admin to create work orders by specifying the product to be manufactured, quantity required, required materials, priority level, and target completion date. | Admin |
| FR-014 | The system shall allow the Admin to create work orders based on order information received from the parent company. | Admin |
| FR-015 | The system shall allow the Admin or Production Supervisor to assign work orders to specific production lines. | Admin, Production Supervisor |
| FR-016 | The system shall track work order status through its lifecycle: Created → Materials Allocated → In Production → Completed → Ready for Shipment. | System |
| FR-017 | The system shall allow the Production Supervisor to view all assigned work orders, prioritize them, and plan daily production schedules. | Production Supervisor |
| FR-018 | The system shall automatically allocate required raw materials from inventory when a work order is moved to "Materials Allocated" status, reducing available inventory accordingly. | System |
| FR-019 | The system shall prevent a work order from proceeding to production if insufficient raw materials are available, and shall notify the Admin and Production Supervisor. | System |
| FR-021 | The system shall allow the Production Supervisor to monitor the progress of all active work orders in real time and confirm work order completion. | Production Supervisor |

### 2.4 Role-Based Access Control and User Management

| ID | Requirement | Roles |
|----|-------------|-------|
| FR-035 | The system shall support four user roles: Company Admin, Receiving/Shipping Clerk, Production Supervisor, and Machine Operator. | System |
| FR-036 | The system shall require all users to authenticate with a username and password before accessing any functionality. | All Roles |
| FR-037 | The system shall restrict access to features and data based on the user's assigned role(s), as defined in the role-permission matrix. | System |
| FR-038 | The system shall allow the Company Admin to create, edit, deactivate, and manage user accounts and role assignments. | Admin |
| FR-039 | The system shall log all user login and logout events with timestamps for audit purposes. | System |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement |
|----|-------------|
| NFR-001 | The system shall load any page within 3 seconds under normal operating conditions on a standard broadband connection. |
| NFR-002 | The system shall process OCR scans and return extracted data within 10 seconds per document. |
| NFR-003 | The system shall support a minimum of 20 concurrent users without degradation in response time. |
| NFR-004 | Inventory updates (receipts, allocations, shipments) shall be reflected in the system within 2 seconds of confirmation. |

### 3.2 Security

| ID | Requirement |
|----|-------------|
| NFR-005 | All user passwords shall be stored using industry-standard hashing algorithms (e.g., bcrypt). |
| NFR-006 | All communication between client and server shall be encrypted using HTTPS/TLS. |
| NFR-007 | The system shall enforce role-based access control on both the frontend (UI visibility) and backend (API authorization). |
| NFR-008 | The system shall automatically log out inactive users after 30 minutes of inactivity. |
| NFR-009 | The system shall maintain audit logs of all data-modifying operations, recording the user, action, timestamp, and affected records. |

### 3.3 Usability

| ID | Requirement |
|----|-------------|
| NFR-010 | The system shall provide a mobile-responsive interface that is fully functional on tablets and smartphones used on the factory floor. |
| NFR-011 | The system shall be designed for users with varying levels of technical proficiency, using clear labels, intuitive navigation, and minimal required training. |
| NFR-012 | The system shall provide confirmation prompts before any destructive or irreversible actions (e.g., deleting a work order, confirming a shipment). |
| NFR-013 | The system shall display real-time feedback and status messages for all user actions (e.g., "Delivery recorded successfully," "Insufficient inventory for work order"). |

### 3.4 Reliability and Availability

| ID | Requirement |
|----|-------------|
| NFR-014 | The system shall target 99% uptime during operating hours (6:00 AM – 10:00 PM local time, Monday–Saturday). |
| NFR-015 | The system shall perform automated daily backups of the PostgreSQL database. |
| NFR-016 | The system shall handle unexpected errors gracefully, displaying user-friendly error messages without exposing technical details. |

### 3.5 Scalability

| ID | Requirement |
|----|-------------|
| NFR-017 | The system architecture shall support the addition of new production lines without requiring structural changes to the database or application logic. |
| NFR-018 | The system shall be designed with a modular architecture that allows new functional modules to be added independently. |

### 3.6 Compatibility

| ID | Requirement |
|----|-------------|
| NFR-019 | The system shall support the latest versions of Chrome, Firefox, Safari, and Edge browsers. |
| NFR-020 | The system shall function on Android and iOS mobile devices through the web browser without requiring a native application. |

### 3.7 Maintainability

| ID | Requirement |
|----|-------------|
| NFR-021 | The system shall separate frontend (Next.js) and backend (FastAPI) into independent deployable components communicating via RESTful APIs. |
| NFR-022 | The system shall include comprehensive API documentation generated from code (e.g., FastAPI's automatic OpenAPI/Swagger documentation). |
| NFR-023 | The codebase shall follow consistent coding standards and include inline documentation for complex business logic. |

---

## 4. Software Requirements Specification

### 4.1 Purpose

This Software Requirements Specification (SRS) describes the system architecture, data model, interface requirements, and use cases for the initial delivery phase of the Integrated Manufacturing Execution System (MES). The complete functional and non-functional requirements for this phase are defined in Sections 2 and 3 of this document.

### 4.2 Definitions, Acronyms, and Abbreviations

| Term | Definition |
|------|-----------|
| MES | Manufacturing Execution System |
| OCR | Optical Character Recognition |
| Bill of Lading | A legal shipping document issued by a carrier that details the type, quantity, and destination of goods being transported. Accompanies all incoming material deliveries and serves as the primary source document for the receiving workflow. |
| BOL | Abbreviation for Bill of Lading. |
| Work Order | A production order specifying what product to manufacture, in what quantity, and with which materials. |
| Lot/Batch Number | A unique identifier assigned to a group of materials or finished goods for traceability. |
| Raw Materials | Unprocessed materials received from suppliers and used in production. |
| Finished Goods | Completed products resulting from the manufacturing process. |
| Production Line | A dedicated manufacturing line (the facility operates five) where raw materials are transformed into finished goods. |

### 4.3 System Architecture Overview

The system follows a client-server architecture with a Next.js frontend communicating with a FastAPI backend via RESTful APIs. Data is persisted in a PostgreSQL relational database. OCR processing is handled server-side using Python-based OCR libraries. The system is deployed as a web application accessible through modern browsers on desktop, tablet, and smartphone devices.

All client-server communication occurs over HTTPS. The frontend communicates with the backend exclusively through RESTful API calls using JSON payloads. No real-time WebSocket connections are required in the initial version; the UI will use polling or on-demand refresh for data updates.

### 4.4 Users, Roles, and Privileges

The system enforces access control through a three-tier model: **Privileges** are the atomic units of permission, **Roles** are named collections of privileges, and **Users** are assigned one or more roles. A user who holds multiple roles receives the union of all privileges granted by those roles.

#### 4.4.1 Privileges

Privileges represent individual, granular permissions to perform an action or access a resource within the system. All access control decisions are evaluated at the privilege level on both the frontend and backend.

| Privilege ID | Privilege Name | Description |
|---|---|---|
| PRV-001 | receiving.create | Create new incoming delivery records |
| PRV-002 | receiving.view | View receiving records and delivery history |
| PRV-003 | receiving.ocr | Upload and process Bill of Lading documents via OCR |
| PRV-004 | inventory.view | View raw material and finished goods inventory |
| PRV-005 | inventory.adjust | Manually adjust inventory quantities |
| PRV-006 | inventory.alerts.manage | Configure low-stock alert thresholds |
| PRV-007 | inventory.trace | Access lot/batch traceability reports |
| PRV-008 | workorder.create | Create new work orders |
| PRV-009 | workorder.view | View work orders and their status |
| PRV-010 | workorder.assign | Assign work orders to production lines |
| PRV-011 | workorder.allocate | Allocate raw materials to a work order |
| PRV-012 | workorder.manage | Update priority, status, and completion of work orders |
| PRV-015 | users.manage | Create, edit, deactivate, and assign roles to user accounts |
| PRV-016 | roles.manage | Create and modify role definitions and privilege assignments |
| PRV-017 | audit.view | View system audit logs |

#### 4.4.2 Roles

Roles are named bundles of privileges that reflect a job function within the facility. The system ships with four predefined roles. Administrators may define additional roles as operational needs evolve.

| Role | Description | Privileges Granted |
|---|---|---|
| Company Admin | Full system access. Manages users, configures settings, creates work orders, and accesses all reports. | All in-scope privileges (PRV-001 through PRV-017) |
| Receiving/Shipping Clerk | Logs incoming material deliveries. | PRV-001, PRV-002, PRV-003, PRV-004 |
| Production Supervisor | Prioritizes and plans work orders, assigns production lines, and monitors active orders. | PRV-004, PRV-007, PRV-009, PRV-010, PRV-011, PRV-012 |
| Machine Operator | Views active work orders assigned to their production line. | PRV-009 |

#### 4.4.3 Users and Multi-Role Assignment

A user account represents an individual who accesses the system. Users are assigned one or more roles through a many-to-many relationship: a single user may hold multiple roles, and a single role may be assigned to many users. When a user holds multiple roles, their effective privilege set is the **union** of all privileges granted by each assigned role — no privilege is duplicated or reduced by holding multiple roles.

**Example:** A user assigned both the *Receiving/Shipping Clerk* and *Production Supervisor* roles would have access to receiving, OCR scanning, inventory viewing, work order management, and lot/batch traceability.

User accounts include the following attributes: username, full name, password (hashed), assigned role(s), preferred language (English or Spanish), account status (active/inactive), and creation timestamp.

### 4.5 System Features Summary

The following summaries describe each functional area and how it maps to the functional requirements defined in Section 2.

**Receiving and Intake (FR-001–FR-005):** The system provides a digital receiving workflow that replaces manual transcription of shipping documents. When a truck delivers raw materials, the Receiving/Shipping Clerk can photograph or scan the bill of lading. The OCR engine extracts supplier information, material descriptions, quantities, and lot numbers, then auto-populates the delivery entry form. The clerk reviews and corrects any OCR errors before confirming the delivery, at which point the system automatically creates inventory records for all received materials. Each delivery line item is directly linked to its resulting inventory record, maintaining a traceable connection from source document to stock.

**Inventory Management (FR-006–FR-012):** The system maintains a centralized, real-time inventory for both raw materials and finished goods. Every inventory-affecting event — receiving, allocation, production consumption, and adjustments — is automatically reflected in stock levels with a full audit trail. The Admin can configure low-stock threshold alerts. Lot/batch traceability allows forward and backward tracing through the production chain: from raw material lot to production run to finished goods batch.

**Work Order Management (FR-013–FR-021):** The Admin creates work orders based on order spreadsheets received from the parent company, specifying the product, quantity, required materials, priority, and target completion date. Work orders progress through a defined lifecycle: Created → Materials Allocated → In Production → Completed → Ready for Shipment. The Production Supervisor views assigned work orders, prioritizes them for the day, and assigns them to production lines. When materials are allocated, the system automatically reduces available inventory.

**Role-Based Access Control (FR-035–FR-039):** The system enforces authentication and role-based authorization. All users must log in with credentials. The Company Admin manages user accounts and role assignments. Users may be assigned multiple roles, with their effective permissions being the union of all assigned role privileges. Each role has a defined permission set that restricts both UI visibility and API-level access. All login/logout events and data-modifying actions are logged for audit purposes.

### 4.6 External Interface Requirements

#### User Interfaces

The system shall provide a web-based interface built with Next.js that is responsive across desktop monitors, tablets, and smartphones. The interface adapts to the user's role, displaying only the modules and data the user is authorized to access. Key interface considerations include large touch targets for factory floor use on mobile devices, clear visual status indicators for work order lifecycle stages, and a dashboard-first design that gives each role immediate visibility into their most relevant information.

#### Hardware Interfaces

The system interacts with device cameras (smartphones, tablets, or dedicated scanners) for capturing images of bills of lading for OCR processing. No specialized hardware is required beyond standard computing and mobile devices with cameras.

#### Software Interfaces

| Interface | Description |
|-----------|-------------|
| OCR Engine | Python-based OCR library (e.g., Tesseract via pytesseract, or a cloud OCR API) for extracting text from bill of lading images. |
| PostgreSQL Database | Relational database for persisting all system data including inventory, work orders, user accounts, and audit trails. |
| FastAPI Backend | RESTful API server handling business logic, authentication, authorization, and database operations. |
| Next.js Frontend | Server-side rendered web application consuming the FastAPI REST endpoints. |

### 4.7 Data Requirements

#### Key Data Entities

| Entity | Description | Key Attributes |
|--------|-------------|---------------|
| User | System user account | user_id, username, password_hash, full_name, status, preferred_language, created_at |
| User Role Assignment | Many-to-many join between users and roles | user_id, role_id, assigned_at |
| Role | Named bundle of privileges | role_id, role_name, description |
| Delivery | Incoming material delivery record | delivery_id, supplier, carrier, delivery_date, bol_reference, created_by, created_at |
| Delivery Item | Individual material line on a delivery; linked to the inventory item it creates | item_id, delivery_id, material_type, quantity, lot_batch_number, storage_location, inventory_item_id |
| Inventory Item | Current stock record; traceable back to the delivery item that created it | inventory_id, material_type, category (raw/finished), quantity_on_hand, lot_batch_number, storage_location, source_delivery_item_id, last_updated |
| Work Order | Production order | work_order_id, product, quantity_required, quantity_produced, priority, status, target_date, production_line, created_by, created_at |
| Work Order Material | Materials required for a work order | id, work_order_id, material_type, quantity_required, quantity_allocated, lot_batch_number |
| Audit Log | System audit trail | log_id, user_id, action, entity_type, entity_id, details, timestamp |

#### Data Retention

All transactional data (deliveries, work orders, and audit logs) shall be retained indefinitely within the system. The Admin may export historical data for archival purposes.

### 4.8 Localization Requirements

The system serves a bilingual workforce. All user-facing text — including labels, navigation, status messages, error messages, confirmation prompts, and form fields — must be available in both English and Spanish.

| ID | Requirement |
|----|-------------|
| LR-001 | The system shall support English and Spanish as selectable interface languages. |
| LR-002 | Users shall be able to set their preferred language in their account profile, which persists across sessions. |
| LR-003 | The system shall default to English for new users until a preference is saved. |
| LR-004 | All UI strings shall be managed through an externalized translation file (i18n) to allow new languages to be added without code changes. |
| LR-005 | All system-generated messages — including confirmations, warnings, errors, and status updates — shall be displayed in the user's selected language. |
| LR-006 | Data values entered by users (e.g., material names, work order notes) shall be stored as entered and are not subject to translation. |
| LR-007 | Date, time, and number formats shall follow the conventions of the selected language locale (e.g., MM/DD/YYYY for English, DD/MM/YYYY for Spanish). |

---

## 5. Use Cases

The table below summarizes all system use cases in scope for this phase.

| Use Case | Title | Functional Area |
|----------|-------|-----------------|
| UC-001 | Receive Incoming Material Delivery | Receiving & Intake |
| UC-002 | View and Search Inventory | Inventory Management |
| UC-003 | Create Work Order | Work Order Management |
| UC-004 | Allocate Materials to Work Order | Work Order Management |
| UC-005 | Plan and Prioritize Daily Production | Work Order Management |
| UC-009 | Manage User Accounts | User Management |
| UC-011 | User Authentication | User Management |

---

### 5.1 Receiving and Intake

### UC-001: Receive Incoming Material Delivery

**Primary Actor:** Receiving/Shipping Clerk
**Preconditions:** User is authenticated and has Receiving/Shipping Clerk or Admin role.
**Related Requirements:** FR-001, FR-002, FR-003, FR-004, FR-005

#### Main Flow

1. A truck arrives at the facility with raw materials and a bill of lading (BOL).
2. The Receiving/Shipping Clerk navigates to the Receiving module and selects "New Delivery."
3. The Clerk photographs or uploads a scan of the BOL.
4. The system processes the image using OCR and extracts supplier name, material descriptions, quantities, lot/batch numbers, and carrier information.
5. The system auto-populates the delivery entry form with the extracted data.
6. The Clerk reviews the populated fields, corrects any inaccuracies, and adds the storage location for each material.
7. The Clerk confirms the delivery.
8. The system creates a delivery record and automatically generates inventory entries for each received material. Each delivery line item is linked to its resulting inventory record via a shared identifier, maintaining full traceability from the BOL to current stock.
9. The system displays a confirmation message: "Delivery recorded successfully. X items added to inventory."

#### Alternate Flow

**A1 — Manual Entry Without OCR (Step 3):**
3a. The Clerk does not have a BOL document to scan (e.g., damaged, missing, or illegible).
3b. The Clerk selects "Manual Entry" and types the delivery information directly into the form fields.
3c. The flow continues at Step 6.

**A2 — Multiple Materials on One BOL (Step 6):**
6a. The BOL contains multiple line items for different materials.
6b. The system displays each material as a separate row in the delivery form.
6c. The Clerk reviews and assigns a storage location to each material individually.
6d. The flow continues at Step 7.

#### Exception Flow

**E1 — OCR Extraction Fails (Step 4):**
4a. The OCR engine cannot extract data from the uploaded image (poor quality, unsupported format, unreadable text).
4b. The system notifies the Clerk: "Unable to extract data from the uploaded document. Please try again with a clearer image or enter data manually."
4c. The Clerk retries with a new image or switches to manual entry (Alternate Flow A1).

**E2 — Duplicate Delivery Detected (Step 7):**
7a. The system detects a potential duplicate based on matching supplier, date, and BOL reference number.
7b. The system warns the Clerk: "A delivery with this BOL reference already exists. Do you want to proceed?"
7c. The Clerk either cancels the entry or confirms it as a legitimate separate delivery.

---

### 5.2 Inventory Management

### UC-002: View and Search Inventory

**Primary Actor:** Company Admin (full access), Production Supervisor, Receiving/Shipping Clerk (view only)
**Preconditions:** User is authenticated with an authorized role.
**Related Requirements:** FR-006, FR-007, FR-011

#### Main Flow

1. The user navigates to the Inventory module.
2. The system displays the inventory dashboard showing summary counts of raw materials and finished goods.
3. The user selects either "Raw Materials" or "Finished Goods" to view detailed listings.
4. The system displays a table of inventory items with columns for material name, quantity on hand, lot/batch number, storage location, and date received (or date produced for finished goods).
5. The user applies filters (material type, lot number, location, date range) or enters a search term.
6. The system updates the displayed results based on the applied filters.

#### Alternate Flow

**A1 — Export Inventory Data (Step 6):**
6a. The user selects "Export" to download the current filtered inventory view.
6b. The system generates a CSV file and downloads it to the user's device.

#### Exception Flow

**E1 — No Results Found (Step 6):**
6a. The applied filters return no matching inventory records.
6b. The system displays: "No inventory items match the selected filters."
6c. The user adjusts filters or clears them to return to the full listing.

---

### 5.3 Work Order Management

### UC-003: Create Work Order

**Primary Actor:** Company Admin
**Preconditions:** User is authenticated with Admin role. Raw materials exist in inventory.
**Related Requirements:** FR-013, FR-014, FR-018, FR-019

#### Main Flow

1. The Admin receives an order spreadsheet from the parent company.
2. The Admin navigates to the Work Order module and selects "Create Work Order."
3. The Admin enters the work order details: product to manufacture, quantity required, required raw materials and quantities, priority level (Low, Medium, High, Urgent), and target completion date.
4. The system validates that sufficient raw materials are available in inventory.
5. The system creates the work order with status "Created."
6. The system displays a confirmation: "Work Order WO-XXXX created successfully."

#### Alternate Flow

**A1 — Partial Material Availability (Step 4):**
4a. The system identifies that some but not all required materials are available in sufficient quantity.
4b. The system displays a warning showing which materials are short and by how much.
4c. The Admin can still create the work order with status "Created" (materials will be allocated later when stock arrives) or cancel.

**A2 — Admin Assigns to Production Line Immediately (Step 6):**
6a. After creation, the Admin assigns the work order to a specific production line.
6b. The system updates the work order with the assigned production line.

#### Exception Flow

**E1 — Insufficient Materials (Step 4):**
4a. The system determines that zero quantity of one or more required materials is available.
4b. The system displays an error: "Cannot create work order. The following materials have zero stock: [list]."
4c. The Admin must either wait for materials to arrive or adjust the work order requirements.

**E2 — Duplicate Work Order (Step 5):**
5a. The system detects a work order with identical product, quantity, and target date already exists.
5b. The system warns the Admin: "A similar work order already exists (WO-XXXX). Do you want to proceed?"
5c. The Admin confirms or cancels.

### UC-004: Allocate Materials to Work Order

**Primary Actor:** Company Admin, Production Supervisor
**Preconditions:** Work order exists with status "Created." Required raw materials are available in inventory.
**Related Requirements:** FR-015, FR-016, FR-018, FR-019

#### Main Flow

1. The Admin or Production Supervisor opens an existing work order with status "Created."
2. The user selects "Allocate Materials."
3. The system displays the required materials list with current available inventory quantities.
4. The user confirms material allocation.
5. The system reserves the required material quantities from inventory, reducing available stock.
6. The system updates the work order status to "Materials Allocated."
7. The system displays confirmation: "Materials allocated successfully."

#### Alternate Flow

**A1 — Partial Allocation (Step 3):**
3a. Available inventory covers some but not all required materials.
3b. The system highlights the shortfalls.
3c. The user can allocate only the available materials and wait for the remaining stock, keeping the status as "Created" until fully allocated.

#### Exception Flow

**E1 — Inventory Changed Since Last Check (Step 5):**
5a. Between viewing and confirming, another user has allocated or consumed the same materials, reducing available stock below the required amount.
5b. The system displays: "Inventory has changed. Insufficient stock for [material]. Please review and try again."
5c. The user returns to Step 3 with updated inventory quantities.

### UC-005: Plan and Prioritize Daily Production

**Primary Actor:** Production Supervisor
**Preconditions:** User is authenticated with Production Supervisor role. Work orders have been created and assigned.
**Related Requirements:** FR-015, FR-017, FR-021

#### Main Flow

1. The Production Supervisor navigates to the Work Order module.
2. The system displays all work orders assigned to the supervisor, grouped by status (Materials Allocated, In Production, Completed).
3. The supervisor reviews the "Materials Allocated" work orders and sets the day's production priority by reordering them.
4. The supervisor assigns each prioritized work order to a specific production line.
5. The system saves the assignments and priorities.
6. The affected work orders become visible to the Machine Operators on their respective production lines.

#### Alternate Flow

**A1 — Reassign Work Order to Different Line (Step 4):**
4a. A production line is down or overloaded.
4b. The supervisor reassigns the work order to a different available production line.
4c. The system updates the assignment and notifies the relevant Machine Operator.

#### Exception Flow

**E1 — No Work Orders Available (Step 2):**
2a. There are no work orders assigned or in a ready state.
2b. The system displays: "No work orders available for scheduling."

**E2 — Production Line at Capacity (Step 4):**
4a. The selected production line already has the maximum number of active work orders.
4b. The system warns: "Production Line X already has [N] active work orders. Do you want to add another?"
4c. The supervisor confirms or selects a different line.

---

### 5.4 User Management and Authentication

### UC-009: Manage User Accounts

**Primary Actor:** Company Admin
**Preconditions:** User is authenticated with Admin role.
**Related Requirements:** FR-035, FR-036, FR-037, FR-038, FR-039

#### Main Flow

1. The Admin navigates to the User Management module.
2. The system displays a list of all user accounts with their names, roles, and status (active/inactive).
3. The Admin selects "Create New User."
4. The Admin enters the new user's information: full name, username, temporary password, and assigns one or more roles.
5. The system creates the user account.
6. The system displays confirmation: "User account created successfully."

#### Alternate Flow

**A1 — Edit Existing User (Step 3):**
3a. The Admin selects an existing user to edit.
3b. The Admin modifies the user's role(s), name, or status.
3c. The system saves the changes and displays confirmation.

**A2 — Deactivate User (Step 3):**
3a. The Admin selects an existing user and chooses "Deactivate."
3b. The system confirms: "Are you sure you want to deactivate this user? They will no longer be able to log in."
3c. The Admin confirms, and the system deactivates the account.

#### Exception Flow

**E1 — Duplicate Username (Step 5):**
5a. The entered username already exists in the system.
5b. The system displays: "Username already exists. Please choose a different username."
5c. The Admin enters a different username.

**E2 — Cannot Deactivate Last Admin (Alternate A2):**
3a. The Admin attempts to deactivate the only remaining Admin account.
3b. The system prevents the action: "Cannot deactivate the last Admin account. At least one Admin must remain active."

### UC-011: User Authentication

**Primary Actor:** All Roles
**Preconditions:** User has been created in the system by the Admin with valid credentials.
**Related Requirements:** FR-036, FR-037, FR-039

#### Main Flow

1. The user navigates to the system login page.
2. The user enters their username and password.
3. The system validates the credentials.
4. The system authenticates the user, creates a session, and logs the login event with a timestamp.
5. The system redirects the user to their role-appropriate dashboard.

#### Alternate Flow

**A1 — Session Timeout (Post-Login):**
5a. The user is logged in but has been inactive for 30 minutes.
5b. The system automatically logs the user out and redirects to the login page.
5c. The system displays: "Your session has expired due to inactivity. Please log in again."

#### Exception Flow

**E1 — Invalid Credentials (Step 3):**
3a. The username or password is incorrect.
3b. The system displays: "Invalid username or password. Please try again."
3c. The user is returned to the login form.

**E2 — Deactivated Account (Step 3):**
3a. The credentials are valid but the account has been deactivated by an Admin.
3b. The system displays: "Your account has been deactivated. Please contact an administrator."

---

## 6. UML Diagrams

### 6.1 Use Case Diagrams

#### System Overview

The system overview use case diagram shows all four user roles and the full set of system functions in scope for this phase, establishing the boundaries of the initial MES delivery.

![System Use Case Overview](docs/diagrams/images/uc_overview.png)

---

#### Receiving & Intake

The receiving use case diagram details the Clerk's workflow for logging material deliveries, including both the OCR-assisted path and the manual entry fallback.

![Receiving & Intake Use Cases](docs/diagrams/images/uc_receiving.png)

---

#### Inventory Management

This diagram shows all roles that access the Inventory module and the available actions: filtered search, export, and inventory browsing by category.

![Inventory Management Use Cases](docs/diagrams/images/uc_inventory.png)

---

#### Work Order Management

This diagram covers the Admin and Production Supervisor interactions with the work order lifecycle, from creation and material allocation to daily scheduling.

![Work Order Management Use Cases](docs/diagrams/images/uc_work_orders.png)

---

#### User Management & Authentication

This diagram covers Admin-only user account management (create, edit, deactivate) and the authentication use case shared by all roles.

![Admin & Authentication Use Cases](docs/diagrams/images/uc_admin.png)

---

### 6.2 Class Diagrams

#### System Overview

The system class diagram shows all major data entities and their relationships for this phase, covering users, roles, inventory, work orders, and the audit trail.

![System Class Overview](docs/diagrams/images/class_overview.png)

---

#### Authentication & Audit Domain

This class diagram details the User, Role, and UserRoleAssignment entities that implement the many-to-many role model, alongside the AuditLog that captures all system events.

![Authentication Class Diagram](docs/diagrams/images/class_auth.png)

---

#### Receiving Domain

This class diagram shows the Delivery, DeliveryItem, and InventoryItem entities and the bidirectional foreign key relationship that links each delivery line item to the inventory record it creates.

![Receiving Class Diagram](docs/diagrams/images/class_receiving.png)

---

#### Work Orders & Materials

This class diagram details the WorkOrder and WorkOrderMaterial entities, the work order status lifecycle, and the relationship to allocated inventory.

![Work Orders Class Diagram](docs/diagrams/images/class_work_orders.png)

---

### 6.3 Sequence Diagrams

#### User Authentication (UC-011)

This sequence diagram shows the login flow — credential validation, session creation, audit log entry, and role-based dashboard redirection — common to all user roles.

![User Authentication Sequence](docs/diagrams/images/seq_authentication.png)

---

#### Manage User Accounts (UC-009)

This sequence diagram covers the Admin's user management flow: creating a new user account, assigning one or more roles, and the system safeguard preventing deactivation of the last Admin.

![Manage Users Sequence](docs/diagrams/images/seq_manage_users.png)

---

#### Receive Material via OCR (UC-001)

This sequence diagram illustrates the OCR-powered receiving workflow: image upload, server-side OCR processing, form auto-population, clerk review and confirmation, and automatic inventory creation with delivery item linkage.

![Receiving OCR Sequence](docs/diagrams/images/seq_receiving_ocr.png)

---

#### Create Work Order (UC-003)

This sequence diagram traces the Admin's work order creation flow, including material availability validation, work order record creation, and the system response for insufficient stock conditions.

![Create Work Order Sequence](docs/diagrams/images/seq_create_work_order.png)

---

#### Allocate Materials to Work Order (UC-004)

This sequence diagram shows the material allocation flow including pessimistic locking to prevent concurrent allocation conflicts, inventory reservation, and work order status update.

![Allocate Materials Sequence](docs/diagrams/images/seq_allocate_materials.png)

---

#### Plan and Prioritize Daily Production (UC-005)

This sequence diagram illustrates the Production Supervisor's scheduling workflow: reordering work orders by priority, assigning them to production lines, and the system capacity check that warns before overloading a line.

![Prioritize Production Sequence](docs/diagrams/images/seq_prioritize_production.png)

---

*End of Document*
