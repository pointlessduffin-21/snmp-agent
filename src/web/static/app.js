// SNMP Agent Monitor - Frontend Application

class SNMPMonitor {
    constructor() {
        this.selectedDevice = null;
        this.devices = [];
        this.eventSource = null;
        this.refreshInterval = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadDevices();
        this.loadStats();
        this.loadMqttStatus();
        this.loadConfig();
        this.startEventStream();
        
        this.startAutoRefresh();
    }

    setupEventListeners() {
        // Scan buttons
        document.getElementById('btn-scan').addEventListener('click', () => this.showScanDialog());
        document.getElementById('btn-quick-scan').addEventListener('click', () => this.quickScan());
        document.getElementById('btn-refresh').addEventListener('click', () => this.refresh());
        document.getElementById('btn-config').addEventListener('click', () => this.showConfig());
        
        // Device details
        document.getElementById('btn-close-details').addEventListener('click', () => this.closeDetails());
        document.getElementById('btn-browse-oids').addEventListener('click', () => {
            if (this.selectedDevice) {
                this.showOidBrowser(this.selectedDevice.device.ip);
            }
        });
        
        // Config modal
        document.getElementById('btn-close-config').addEventListener('click', () => this.closeConfig());
        document.getElementById('btn-save-config').addEventListener('click', () => this.saveConfig());
        document.getElementById('btn-cancel-config').addEventListener('click', () => this.closeConfig());
        
        // Filters
        document.getElementById('filter-online').addEventListener('change', () => this.applyFilters());
        document.getElementById('filter-offline').addEventListener('change', () => this.applyFilters());
        
        // MQTT Manager
        document.getElementById('btn-mqtt-manager')?.addEventListener('click', () => this.showMqttManager());
        document.getElementById('btn-close-mqtt-manager')?.addEventListener('click', () => this.closeMqttManager());
        document.getElementById('btn-cancel-mqtt-manager')?.addEventListener('click', () => this.closeMqttManager());
        document.getElementById('btn-save-mqtt-devices')?.addEventListener('click', () => this.saveMqttDevices());
    }

    async loadDevices() {
        try {
            const response = await fetch('/api/devices');
            this.devices = await response.json();
            this.renderDevices();
            this.updateLastUpdate();
        } catch (error) {
            console.error('Failed to load devices:', error);
            this.showError('Failed to load devices');
        }
    }

    async loadStats() {
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();
            
            document.getElementById('stat-devices').textContent = stats.machine_count || 0;
            document.getElementById('stat-online').textContent = stats.online_count || 0;
            document.getElementById('stat-cpu').textContent = (stats.avg_cpu_percent || 0).toFixed(1) + '%';
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    }

    async loadMqttStatus() {
        try {
            const response = await fetch('/api/mqtt/status');
            const mqtt = await response.json();
            
            const statusEl = document.getElementById('mqtt-status');
            const portEl = document.getElementById('mqtt-port');
            const clientsEl = document.getElementById('mqtt-clients');
            
            if (statusEl) {
                statusEl.textContent = mqtt.status || 'unknown';
                statusEl.className = 'status-badge ' + (mqtt.status === 'running' ? 'online' : 'offline');
            }
            if (portEl) portEl.textContent = mqtt.port || '-';
            if (clientsEl) clientsEl.textContent = mqtt.clients || 0;
        } catch (error) {
            console.error('Failed to load MQTT status:', error);
        }
    }

    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            this.config = await response.json();
            this.startAutoRefresh();
        } catch (error) {
            console.error('Failed to load config:', error);
        }
    }

    renderDevices() {
        const grid = document.getElementById('device-grid');
        grid.innerHTML = '';

        const filteredDevices = this.filterDevices();

        if (filteredDevices.length === 0) {
            grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 2rem; color: var(--text-secondary);">No devices found</div>';
            return;
        }

        filteredDevices.forEach(device => {
            const card = this.createDeviceCard(device);
            grid.appendChild(card);
        });
    }

    createDeviceCard(device) {
        const card = document.createElement('div');
        
        // Determine status class: snmp-active (green), online (orange), offline (red)
        let statusClass, statusText;
        if (!device.is_online) {
            statusClass = 'offline';
            statusText = 'Offline';
        } else if (device.snmp_active) {
            statusClass = 'snmp-active';
            statusText = 'SNMP Active';
        } else {
            statusClass = 'online-no-snmp';
            statusText = 'Online';
        }
        
        card.className = `device-card ${statusClass}`;
        
        const uptime = this.formatUptime(device.uptime_seconds);
        
        // Use display_name or fallback to best available name
        const displayName = device.display_name && device.display_name !== 'unknown' && device.display_name !== device.ip
            ? device.display_name
            : (device.netbios_name || device.mdns_name || device.dns_name || device.hostname || device.ip);
        const finalName = displayName !== 'unknown' ? displayName : device.ip;
        
        const vendorText = device.vendor && device.vendor !== 'Unknown' ? device.vendor : '';
        const macText = device.mac_address || '';
        const osText = device.os_type && device.os_type !== 'unknown' ? device.os_type : '';
        
        // Show resolved names as tooltip/subtitle
        const nameLabels = [];
        if (device.netbios_name) nameLabels.push(`SMB: ${device.netbios_name}`);
        if (device.mdns_name) nameLabels.push(`mDNS: ${device.mdns_name}`);
        if (device.dns_name) nameLabels.push(`DNS: ${device.dns_name}`);
        const namesSubtitle = nameLabels.length > 0 ? nameLabels.join(' | ') : '';
        
        card.innerHTML = `
            <div class="device-header">
                <div class="device-name-group">
                    <div class="device-name">${finalName}</div>
                    ${namesSubtitle ? `<div class="device-names-subtitle">${namesSubtitle}</div>` : ''}
                </div>
                <div class="device-status ${statusClass}">
                    ${statusText}
                </div>
            </div>
            <div class="device-info">
                <div class="device-row">🌐 ${device.ip}</div>
                ${macText ? `<div class="device-mac">📟 ${macText}</div>` : ''}
                ${osText ? `<div class="device-row">💻 ${osText}</div>` : ''}
                ${vendorText ? `<div class="device-row">🏭 ${vendorText}</div>` : ''}
                <div class="device-row">⏱️ ${uptime}</div>
                <div class="device-method">via ${device.collection_method}</div>
            </div>
        `;
        
        card.addEventListener('click', () => this.showDeviceDetails(device.ip));
        
        return card;
    }

    showDeviceDetails(ip) {
        // Navigate to dedicated device page
        window.location.href = `/device/${ip}`;
    }

    renderDeviceDetails(data) {
        const { device, cpu, memory, storage } = data;
        
        // System info
        document.getElementById('details-title').textContent = `${device.hostname} (${device.ip})`;
        document.getElementById('detail-ip').textContent = device.ip;
        document.getElementById('detail-hostname').textContent = device.hostname;
        document.getElementById('detail-os').textContent = device.os_type;
        document.getElementById('detail-uptime').textContent = this.formatUptime(device.uptime_seconds);
        
        // CPU metrics
        document.getElementById('cpu-usage-text').textContent = cpu.usage_percent.toFixed(1) + '%';
        const cpuBar = document.getElementById('cpu-usage-bar');
        cpuBar.style.width = cpu.usage_percent + '%';
        cpuBar.className = 'progress-fill ' + this.getUsageClass(cpu.usage_percent);
        
        document.getElementById('cpu-model').textContent = cpu.model_name || 'Unknown';
        document.getElementById('cpu-cores').textContent = `${cpu.core_count} cores / ${cpu.thread_count} threads`;
        document.getElementById('cpu-freq').textContent = cpu.frequency_mhz ? `${cpu.frequency_mhz.toFixed(0)} MHz` : '-';
        document.getElementById('cpu-temp').textContent = cpu.temperature_celsius ? `${cpu.temperature_celsius.toFixed(1)}°C` : 'N/A';
        
        // Memory metrics
        document.getElementById('mem-usage-text').textContent = `${memory.used_gb.toFixed(1)} / ${memory.total_gb.toFixed(1)} GB`;
        const memBar = document.getElementById('mem-usage-bar');
        memBar.style.width = memory.usage_percent + '%';
        memBar.className = 'progress-fill ' + this.getUsageClass(memory.usage_percent);
        
        document.getElementById('mem-total').textContent = memory.total_gb.toFixed(1) + ' GB';
        document.getElementById('mem-used').textContent = memory.used_gb.toFixed(1) + ' GB';
        document.getElementById('mem-available').textContent = memory.available_gb.toFixed(1) + ' GB';
        
        // Storage devices
        const storageList = document.getElementById('storage-list');
        storageList.innerHTML = '';
        
        if (storage.length === 0) {
            storageList.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.875rem;">No storage devices found</div>';
        } else {
            storage.forEach(device => {
                const item = document.createElement('div');
                item.className = 'storage-item';
                item.innerHTML = `
                    <div class="storage-header">
                        <div class="storage-device">${device.device}</div>
                        <div class="storage-type">${device.fs_type} ${device.is_ssd ? '(SSD)' : ''}</div>
                    </div>
                    <div class="storage-header">
                        <span>${device.mount_point}</span>
                        <span>${device.used_gb.toFixed(1)} / ${device.total_gb.toFixed(1)} GB (${device.usage_percent.toFixed(1)}%)</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill ${this.getUsageClass(device.usage_percent)}" style="width: ${device.usage_percent}%"></div>
                    </div>
                `;
                storageList.appendChild(item);
            });
        }
    }

    closeDetails() {
        document.getElementById('device-details').style.display = 'none';
        this.selectedDevice = null;
    }

    async quickScan() {
        const subnet = document.getElementById('subnet-input').value.trim();
        
        if (!subnet) {
            alert('Please enter a subnet (e.g., 192.168.0.0/24)');
            return;
        }
        
        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    subnets: [subnet],
                    timeout_ms: 1000
                })
            });
            
            if (response.ok) {
                this.showSuccess('Scan started for ' + subnet + '. Page will reload in 3 seconds...');
                // Reload page after 3 seconds to show new devices
                setTimeout(() => window.location.reload(), 3000);
            }
        } catch (error) {
            console.error('Scan failed:', error);
            this.showError('Scan failed');
        }
    }

    showScanDialog() {
        const subnet = prompt('Enter subnet to scan (e.g., 192.168.0.0/24):', '192.168.0.0/24');
        if (subnet) {
            document.getElementById('subnet-input').value = subnet;
            this.quickScan();
        }
    }

    startAutoRefresh() {
        if (this.refreshInterval) clearInterval(this.refreshInterval);
        
        let intervalMs = 5000;
        if (this.config && this.config.collection_interval) {
            intervalMs = this.config.collection_interval * 1000;
        }
        
        if (intervalMs < 1000) intervalMs = 1000;
        
        this.refreshInterval = setInterval(() => {
            this.loadDevices();
            this.loadStats();
            this.loadMqttStatus();
        }, intervalMs);
    }

    async refresh() {
        this.showSuccess('Refreshing data...');
        await this.loadDevices();
        await this.loadStats();
        
        if (this.selectedDevice) {
            await this.showDeviceDetails(this.selectedDevice.device.ip);
        }
    }

    showConfig() {
        if (this.config) {
            document.getElementById('config-community').value = this.config.snmp_community || '';
            
            // Handle interval units
            const interval = this.config.collection_interval || 60;
            const unitSelect = document.getElementById('config-interval-unit');
            const intervalInput = document.getElementById('config-interval');
            
            if (interval >= 60 && interval % 60 === 0) {
                unitSelect.value = "60";
                intervalInput.value = interval / 60;
            } else {
                unitSelect.value = "1";
                intervalInput.value = interval;
            }
            
            document.getElementById('config-discovery').checked = this.config.discovery_enabled || false;
            document.getElementById('config-snmp').checked = this.config.collect_remote_snmp || false;
        }
        
        document.getElementById('config-modal').classList.add('show');
    }

    closeConfig() {
        document.getElementById('config-modal').classList.remove('show');
    }

    async saveConfig() {
        const intervalVal = parseInt(document.getElementById('config-interval').value);
        const intervalUnit = parseInt(document.getElementById('config-interval-unit').value);
        
        const update = {
            snmp_community: document.getElementById('config-community').value,
            collection_interval: intervalVal * intervalUnit,
            discovery_enabled: document.getElementById('config-discovery').checked,
            collect_remote_snmp: document.getElementById('config-snmp').checked,
        };
        
        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(update)
            });
            
            if (response.ok) {
                this.showSuccess('Configuration updated');
                this.closeConfig();
                await this.loadConfig();
            }
        } catch (error) {
            console.error('Config save failed:', error);
            this.showError('Failed to save configuration');
        }
    }

    filterDevices() {
        const showOnline = document.getElementById('filter-online').checked;
        const showOffline = document.getElementById('filter-offline').checked;
        
        return this.devices.filter(device => {
            if (device.is_online && !showOnline) return false;
            if (!device.is_online && !showOffline) return false;
            return true;
        });
    }

    applyFilters() {
        this.renderDevices();
    }

    startEventStream() {
        try {
            this.eventSource = new EventSource('/api/stream');
            
            this.eventSource.onmessage = (event) => {
                const stats = JSON.parse(event.data);
                document.getElementById('stat-devices').textContent = stats.machine_count || 0;
                document.getElementById('stat-online').textContent = stats.online_count || 0;
                document.getElementById('stat-cpu').textContent = (stats.avg_cpu_percent || 0).toFixed(1) + '%';
                this.updateConnectionStatus(true);
            };
            
            this.eventSource.onerror = () => {
                this.updateConnectionStatus(false);
                // Reconnect after 5 seconds
                setTimeout(() => {
                    this.eventSource.close();
                    this.startEventStream();
                }, 5000);
            };
        } catch (error) {
            console.error('Event stream error:', error);
        }
    }

    updateConnectionStatus(online) {
        const status = document.getElementById('connection-status');
        status.className = online ? 'status online' : 'status offline';
        status.querySelector('span:last-child').textContent = online ? 'Connected' : 'Disconnected';
    }

    updateLastUpdate() {
        const now = new Date();
        document.getElementById('last-update').textContent = 
            `Last update: ${now.toLocaleTimeString()}`;
    }

    formatUptime(seconds) {
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        
        if (days > 0) return `${days}d ${hours}h`;
        if (hours > 0) return `${hours}h ${mins}m`;
        return `${mins}m`;
    }

    getUsageClass(percent) {
        if (percent >= 90) return 'high';
        if (percent >= 70) return 'medium';
        return '';
    }

    // MQTT Manager
    async showMqttManager() {
        const list = document.getElementById('mqtt-device-list');
        list.innerHTML = '<div class="loading">Loading devices...</div>';
        document.getElementById('mqtt-manager-modal').classList.add('show');
        
        try {
            // Load devices and their MQTT configs
            const [devicesRes, configsRes] = await Promise.all([
                fetch('/api/devices'),
                fetch('/api/mqtt/devices')
            ]);
            
            const devices = await devicesRes.json();
            const configs = await configsRes.json();
            
            const configMap = {};
            configs.forEach(c => configMap[c.device_ip] = c);
            
            list.innerHTML = devices.map(device => {
                const config = configMap[device.ip] || { enabled: false };
                return `
                    <div class="mqtt-device-item">
                        <label class="checkbox-label">
                            <input type="checkbox" 
                                   class="mqtt-device-checkbox" 
                                   data-ip="${device.ip}"
                                   ${config.enabled ? 'checked' : ''} />
                            <div class="device-info">
                                <span class="device-name">${device.hostname}</span>
                                <span class="device-ip">${device.ip}</span>
                            </div>
                        </label>
                    </div>
                `;
            }).join('') || '<div class="no-data">No devices found</div>';
        } catch (error) {
            list.innerHTML = '<div class="error">Failed to load devices</div>';
        }
    }

    closeMqttManager() {
        document.getElementById('mqtt-manager-modal').classList.remove('show');
    }

    async saveMqttDevices() {
        const checkboxes = document.querySelectorAll('.mqtt-device-checkbox');
        const savePromises = [];
        
        checkboxes.forEach(cb => {
            const config = {
                device_ip: cb.dataset.ip,
                enabled: cb.checked,
                publish_cpu: true,
                publish_memory: true,
                publish_storage: true,
                publish_widgets: true
            };
            savePromises.push(
                fetch('/api/mqtt/devices', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                })
            );
        });
        
        try {
            await Promise.all(savePromises);
            this.showSuccess('MQTT settings saved!');
            this.closeMqttManager();
        } catch (error) {
            this.showError('Failed to save MQTT settings');
        }
    }

    showSuccess(message) {
        this.showToast(message, 'success');
    }

    showError(message) {
        this.showToast(message, 'error');
    }
    
    showToast(message, type = 'info') {
        // Create toast element
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
        // Add to body
        document.body.appendChild(toast);
        
        // Animate in
        setTimeout(() => toast.classList.add('show'), 100);
        
        // Remove after 4 seconds
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // OID Browser functionality
    async showOidBrowser(ip) {
        // Create modal if it doesn't exist
        let modal = document.getElementById('oid-browser-modal');
        if (!modal) {
            modal = this.createOidBrowserModal();
            document.body.appendChild(modal);
        }
        
        // Store current device IP
        this.oidBrowserIp = ip;
        
        // Update modal title
        modal.querySelector('.oid-modal-title').textContent = `OID Browser - ${ip}`;
        
        // Show modal
        modal.classList.add('show');
        
        // Load categories
        await this.loadOidCategories(ip);
    }

    createOidBrowserModal() {
        const modal = document.createElement('div');
        modal.id = 'oid-browser-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content oid-browser-content">
                <div class="modal-header">
                    <h2 class="oid-modal-title">OID Browser</h2>
                    <button class="btn-close" onclick="document.getElementById('oid-browser-modal').classList.remove('show')">&times;</button>
                </div>
                <div class="oid-browser-body">
                    <div class="oid-categories">
                        <h3>MIB Categories</h3>
                        <div id="oid-category-list" class="category-list"></div>
                        <div class="oid-actions">
                            <button id="btn-scan-all-oids" class="btn btn-primary">Scan All Categories</button>
                            <button id="btn-custom-oid" class="btn btn-secondary">Custom OID Walk</button>
                        </div>
                    </div>
                    <div class="oid-results">
                        <div class="oid-results-header">
                            <h3>Discovered OIDs <span id="oid-count">(0)</span></h3>
                            <div class="oid-search">
                                <input type="text" id="oid-search" placeholder="Filter OIDs...">
                            </div>
                        </div>
                        <div id="oid-results-list" class="oid-list">
                            <div class="oid-placeholder">Select a category or scan to discover available OIDs</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Add event listeners
        modal.querySelector('#btn-scan-all-oids').addEventListener('click', () => this.scanAllOids());
        modal.querySelector('#btn-custom-oid').addEventListener('click', () => this.customOidWalk());
        modal.querySelector('#oid-search').addEventListener('input', (e) => this.filterOidResults(e.target.value));
        
        return modal;
    }

    async loadOidCategories(ip) {
        try {
            const response = await fetch(`/api/devices/${ip}/oids/categories`);
            const data = await response.json();
            
            const list = document.getElementById('oid-category-list');
            list.innerHTML = data.categories.map(cat => `
                <div class="category-item" data-oid="${cat.oid_prefix}">
                    <label>
                        <input type="checkbox" class="oid-category-checkbox" value="${cat.oid_prefix}">
                        <strong>${cat.id}</strong>
                    </label>
                    <small>${cat.description}</small>
                </div>
            `).join('');
            
            // Add click handlers for categories
            list.querySelectorAll('.category-item').forEach(item => {
                item.addEventListener('dblclick', () => {
                    const oid = item.dataset.oid;
                    this.scanOidCategory(oid);
                });
            });
            
        } catch (error) {
            console.error('Failed to load OID categories:', error);
            this.showError('Failed to load OID categories');
        }
    }

    async scanOidCategory(baseOid) {
        const ip = this.oidBrowserIp;
        if (!ip) return;
        
        this.showOidLoading();
        
        try {
            const response = await fetch(`/api/devices/${ip}/oids/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base_oids: [baseOid],
                    max_results: 200
                })
            });
            
            const data = await response.json();
            this.renderOidResults(data);
            
        } catch (error) {
            console.error('OID scan failed:', error);
            this.showError('OID scan failed');
        }
    }

    async scanAllOids() {
        const ip = this.oidBrowserIp;
        if (!ip) return;
        
        // Get selected categories
        const checkboxes = document.querySelectorAll('.oid-category-checkbox:checked');
        let baseOids = Array.from(checkboxes).map(cb => cb.value);
        
        // If none selected, use first 3 common ones
        if (baseOids.length === 0) {
            baseOids = null; // Will use defaults on server
        }
        
        this.showOidLoading();
        
        try {
            const response = await fetch(`/api/devices/${ip}/oids/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base_oids: baseOids,
                    max_results: 500
                })
            });
            
            const data = await response.json();
            this.renderOidResults(data);
            
        } catch (error) {
            console.error('OID scan failed:', error);
            this.showError('OID scan failed');
        }
    }

    async customOidWalk() {
        const ip = this.oidBrowserIp;
        const oid = prompt('Enter OID to walk (e.g., 1.3.6.1.2.1.1):', '1.3.6.1.2.1.1');
        if (!oid) return;
        
        this.showOidLoading();
        
        try {
            const response = await fetch(`/api/devices/${ip}/oids/walk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base_oid: oid,
                    max_results: 100
                })
            });
            
            const data = await response.json();
            this.renderOidWalkResults(data);
            
        } catch (error) {
            console.error('OID walk failed:', error);
            this.showError('OID walk failed');
        }
    }

    showOidLoading() {
        const list = document.getElementById('oid-results-list');
        list.innerHTML = '<div class="oid-loading">🔍 Scanning OIDs...</div>';
        document.getElementById('oid-count').textContent = '';
    }

    renderOidResults(data) {
        this.currentOidData = data;
        const list = document.getElementById('oid-results-list');
        document.getElementById('oid-count').textContent = `(${data.total_oids} OIDs)`;
        
        if (data.total_oids === 0) {
            list.innerHTML = '<div class="oid-placeholder">No OIDs found for the selected categories</div>';
            return;
        }
        
        let html = '';
        for (const [category, oids] of Object.entries(data.categories)) {
            html += `
                <div class="oid-category-group">
                    <div class="oid-category-header" onclick="this.parentElement.classList.toggle('collapsed')">
                        <span class="expand-icon">▼</span>
                        <strong>${category}</strong>
                        <span class="oid-category-count">(${oids.length})</span>
                    </div>
                    <div class="oid-category-items">
                        ${oids.map(oid => this.renderOidItem(oid)).join('')}
                    </div>
                </div>
            `;
        }
        
        list.innerHTML = html;
    }

    renderOidWalkResults(data) {
        const list = document.getElementById('oid-results-list');
        document.getElementById('oid-count').textContent = `(${data.count} OIDs)`;
        
        if (data.count === 0) {
            list.innerHTML = '<div class="oid-placeholder">No OIDs found under this tree</div>';
            return;
        }
        
        list.innerHTML = `
            <div class="oid-category-group">
                <div class="oid-category-header">
                    <strong>Walk: ${data.base_oid}</strong>
                    <span class="oid-category-count">(${data.count})</span>
                </div>
                <div class="oid-category-items">
                    ${data.oids.map(oid => this.renderOidItem(oid)).join('')}
                </div>
            </div>
        `;
    }

    renderOidItem(oid) {
        const typeClass = oid.value_type === 'integer' ? 'numeric' : oid.value_type === 'float' ? 'numeric' : 'string';
        return `
            <div class="oid-item" data-oid="${oid.oid}">
                <div class="oid-item-header">
                    <span class="oid-name">${oid.name}</span>
                    <span class="oid-type ${typeClass}">${oid.value_type}</span>
                </div>
                <div class="oid-item-details">
                    <code class="oid-string" title="Click to copy" onclick="navigator.clipboard.writeText('${oid.oid}')">${oid.oid}</code>
                    <span class="oid-value">${oid.value}</span>
                </div>
            </div>
        `;
    }

    filterOidResults(query) {
        if (!this.currentOidData) return;
        
        const items = document.querySelectorAll('.oid-item');
        const lowerQuery = query.toLowerCase();
        
        items.forEach(item => {
            const oid = item.dataset.oid.toLowerCase();
            const name = item.querySelector('.oid-name').textContent.toLowerCase();
            const value = item.querySelector('.oid-value').textContent.toLowerCase();
            
            if (oid.includes(lowerQuery) || name.includes(lowerQuery) || value.includes(lowerQuery)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => new SNMPMonitor());
} else {
    new SNMPMonitor();
}
