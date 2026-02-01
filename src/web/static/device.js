// Device Detail Page Controller

class DeviceMonitor {
    constructor() {
        this.deviceIp = this.getDeviceIpFromUrl();
        this.deviceData = null;
        this.widgets = [];
        this.mqttConfig = null;
        this.refreshInterval = null;
        
        if (!this.deviceIp) {
            window.location.href = '/';
            return;
        }
        
        this.init();
    }

    getDeviceIpFromUrl() {
        const path = window.location.pathname;
        const match = path.match(/\/device\/(.+)/);
        return match ? match[1] : null;
    }

    init() {
        this.setupEventListeners();
        this.loadDeviceData();
        this.loadWidgets();
        this.loadMqttConfig();
        this.startAutoRefresh();
    }

    setupEventListeners() {
        // Tab navigation
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });

        // Action buttons
        document.getElementById('btn-refresh').addEventListener('click', () => this.loadDeviceData());
        document.getElementById('btn-browse-oids').addEventListener('click', () => this.openOidBrowser());
        document.getElementById('btn-mqtt-settings').addEventListener('click', () => this.switchTab('mqtt'));
        document.getElementById('btn-add-widget')?.addEventListener('click', () => this.openOidBrowser());

        // OID Browser
        document.getElementById('btn-close-oid-browser').addEventListener('click', () => this.closeOidBrowser());
        document.getElementById('btn-get-oid').addEventListener('click', () => this.getOidValue());
        document.getElementById('btn-walk-oid').addEventListener('click', () => this.walkOidSubtree());
        document.getElementById('btn-scan-all-oids').addEventListener('click', () => this.scanAllOids());
        document.getElementById('oid-search').addEventListener('input', (e) => this.filterOidResults(e.target.value));
        
        document.querySelectorAll('.oid-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById('oid-input').value = btn.dataset.oid;
            });
        });

        // MQTT Settings
        document.getElementById('btn-save-mqtt').addEventListener('click', () => this.saveMqttConfig());
        document.getElementById('mqtt-enabled').addEventListener('change', (e) => {
            document.getElementById('mqtt-device-status').textContent = e.target.checked ? 'Enabled' : 'Disabled';
            document.getElementById('mqtt-device-status').className = 'status-badge ' + (e.target.checked ? 'online' : 'offline');
        });
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        document.getElementById(`tab-${tabName}`).classList.add('active');
    }

    async loadDeviceData() {
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/metrics`);
            
            if (!response.ok) {
                if (response.status === 404) {
                    this.showError('Device not found or no metrics available');
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }
            
            this.deviceData = await response.json();
            this.renderDeviceData();
            this.updateLastUpdate();
        } catch (error) {
            console.error('Failed to load device data:', error);
            this.showError('Failed to load device data');
        }
    }

    renderDeviceData() {
        const { device, cpu, memory, storage } = this.deviceData;
        
        // Update header
        document.getElementById('device-title').textContent = `${device.hostname} (${device.ip})`;
        document.getElementById('device-status').textContent = device.is_online ? 'Online' : 'Offline';
        document.getElementById('device-status').className = 'status-badge ' + (device.is_online ? 'online' : 'offline');
        
        // System info
        document.getElementById('detail-ip').textContent = device.ip;
        document.getElementById('detail-hostname').textContent = device.hostname;
        document.getElementById('detail-os').textContent = device.os_type;
        document.getElementById('detail-uptime').textContent = this.formatUptime(device.uptime_seconds);
        document.getElementById('detail-method').textContent = device.collection_method;
        
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
        this.renderStorageDevices(storage);
    }

    renderStorageDevices(storage) {
        const storageList = document.getElementById('storage-list');
        storageList.innerHTML = '';
        
        if (storage.length === 0) {
            storageList.innerHTML = '<div class="no-data">No storage devices found</div>';
            return;
        }
        
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

    async loadWidgets() {
        try {
            const response = await fetch(`/api/widgets?device_ip=${this.deviceIp}`);
            if (response.ok) {
                this.widgets = await response.json();
                this.renderWidgets();
            }
        } catch (error) {
            console.error('Failed to load widgets:', error);
        }
    }

    renderWidgets() {
        const grid = document.getElementById('widgets-grid');
        
        if (this.widgets.length === 0) {
            grid.innerHTML = `
                <div class="widget-placeholder">
                    <span>No custom widgets yet</span>
                    <button id="btn-add-widget" class="btn btn-small" onclick="monitor.openOidBrowser()">+ Add Widget from OID Browser</button>
                </div>
            `;
            return;
        }
        
        grid.innerHTML = '';
        this.widgets.forEach(widget => {
            const card = document.createElement('div');
            card.className = 'widget-card';
            card.innerHTML = `
                <div class="widget-header">
                    <span class="widget-name">${widget.name}</span>
                    <button class="btn-icon" onclick="monitor.deleteWidget('${widget.id}')">✕</button>
                </div>
                <div class="widget-value" id="widget-${widget.id}">Loading...</div>
                <div class="widget-oid">${widget.oid}</div>
            `;
            grid.appendChild(card);
            
            // Load widget value
            this.loadWidgetValue(widget);
        });
    }

    async loadWidgetValue(widget) {
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/oids/get`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ oids: [widget.oid] })
            });
            
            if (response.ok) {
                const data = await response.json();
                const el = document.getElementById(`widget-${widget.id}`);
                if (el) {
                    const value = data.oids && data.oids[0] ? data.oids[0].value : 'No data';
                    el.textContent = value || 'No data';
                }
            }
        } catch (error) {
            console.error('Failed to load widget value:', error);
        }
    }

    async addWidget(oid, name) {
        try {
            const response = await fetch('/api/widgets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_ip: this.deviceIp,
                    oid: oid,
                    name: name || `OID: ${oid}`,
                    display_type: 'text'
                })
            });
            
            if (response.ok) {
                this.showSuccess('Widget added!');
                this.loadWidgets();
                this.switchTab('widgets');
            }
        } catch (error) {
            this.showError('Failed to add widget');
        }
    }

    async deleteWidget(widgetId) {
        try {
            const response = await fetch(`/api/widgets/${widgetId}`, { method: 'DELETE' });
            if (response.ok) {
                this.showSuccess('Widget removed');
                this.loadWidgets();
            }
        } catch (error) {
            this.showError('Failed to delete widget');
        }
    }

    async loadMqttConfig() {
        try {
            const response = await fetch(`/api/mqtt/devices/${this.deviceIp}`);
            if (response.ok) {
                this.mqttConfig = await response.json();
                this.renderMqttConfig();
            }
        } catch (error) {
            console.error('Failed to load MQTT config:', error);
        }
    }

    renderMqttConfig() {
        if (!this.mqttConfig) return;
        
        document.getElementById('mqtt-enabled').checked = this.mqttConfig.enabled;
        document.getElementById('mqtt-topic').value = this.mqttConfig.topic || `snmp-agent/devices/${this.deviceIp}`;
        document.getElementById('mqtt-pub-cpu').checked = this.mqttConfig.publish_cpu !== false;
        document.getElementById('mqtt-pub-memory').checked = this.mqttConfig.publish_memory !== false;
        document.getElementById('mqtt-pub-storage').checked = this.mqttConfig.publish_storage !== false;
        document.getElementById('mqtt-pub-widgets').checked = this.mqttConfig.publish_widgets !== false;
        
        const status = document.getElementById('mqtt-device-status');
        status.textContent = this.mqttConfig.enabled ? 'Enabled' : 'Disabled';
        status.className = 'status-badge ' + (this.mqttConfig.enabled ? 'online' : 'offline');
    }

    async saveMqttConfig() {
        const config = {
            device_ip: this.deviceIp,
            enabled: document.getElementById('mqtt-enabled').checked,
            topic: document.getElementById('mqtt-topic').value,
            publish_cpu: document.getElementById('mqtt-pub-cpu').checked,
            publish_memory: document.getElementById('mqtt-pub-memory').checked,
            publish_storage: document.getElementById('mqtt-pub-storage').checked,
            publish_widgets: document.getElementById('mqtt-pub-widgets').checked
        };
        
        try {
            const response = await fetch('/api/mqtt/devices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            
            if (response.ok) {
                this.mqttConfig = config;
                this.showSuccess('MQTT settings saved');
            }
        } catch (error) {
            this.showError('Failed to save MQTT settings');
        }
    }

    // OID Browser
    openOidBrowser() {
        document.getElementById('oid-browser-modal').classList.add('show');
        this.loadOidCategories();
    }

    closeOidBrowser() {
        document.getElementById('oid-browser-modal').classList.remove('show');
    }

    async loadOidCategories() {
        const list = document.getElementById('oid-category-list');
        list.innerHTML = '<div class="loading">Loading categories...</div>';
        
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/oids/categories`);
            const data = await response.json();
            
            list.innerHTML = data.categories.map(cat => `
                <div class="category-item">
                    <label>
                        <input type="checkbox" class="oid-category-checkbox" value="${cat.oid_prefix}" checked>
                        <strong>${cat.id}</strong>
                    </label>
                    <small>${cat.description}</small>
                </div>
            `).join('');
        } catch (error) {
            console.error('Failed to load OID categories:', error);
            list.innerHTML = '<div class="error">Failed to load categories</div>';
        }
    }

    async scanAllOids() {
        // Get selected categories
        const checkboxes = document.querySelectorAll('.oid-category-checkbox:checked');
        const baseOids = Array.from(checkboxes).map(cb => cb.value);
        
        if (baseOids.length === 0) {
            this.showError('Please select at least one category');
            return;
        }
        
        const resultsDiv = document.getElementById('oid-results');
        resultsDiv.innerHTML = '<div class="loading">🔍 Scanning all OIDs...</div>';
        document.getElementById('oid-count').textContent = '';
        
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/oids/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base_oids: baseOids,
                    max_results: 500
                })
            });
            
            const data = await response.json();
            this.currentOidData = data;
            this.renderScanResults(data);
        } catch (error) {
            console.error('OID scan failed:', error);
            resultsDiv.innerHTML = '<div class="error">Failed to scan OIDs</div>';
        }
    }

    renderScanResults(data) {
        const resultsDiv = document.getElementById('oid-results');
        document.getElementById('oid-count').textContent = `(${data.total_oids} found)`;
        
        if (data.total_oids === 0) {
            resultsDiv.innerHTML = '<div class="no-data">No OIDs found for the selected categories</div>';
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
                        ${oids.map(oid => `
                            <div class="oid-item" data-oid="${oid.oid}">
                                <div class="oid-item-header">
                                    <span class="oid-name">${oid.name}</span>
                                    <button class="btn btn-small" onclick="monitor.promptAddWidget('${oid.oid}')">+ Widget</button>
                                </div>
                                <div class="oid-item-details">
                                    <code class="oid-string" onclick="navigator.clipboard.writeText('${oid.oid}');monitor.showSuccess('Copied!')">${oid.oid}</code>
                                    <span class="oid-value">${oid.value}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        resultsDiv.innerHTML = html;
    }

    filterOidResults(query) {
        const items = document.querySelectorAll('.oid-item');
        const lowerQuery = query.toLowerCase();
        
        items.forEach(item => {
            const oid = item.dataset.oid?.toLowerCase() || '';
            const name = item.querySelector('.oid-name')?.textContent.toLowerCase() || '';
            const value = item.querySelector('.oid-value')?.textContent.toLowerCase() || '';
            
            if (oid.includes(lowerQuery) || name.includes(lowerQuery) || value.includes(lowerQuery)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }

    async getOidValue() {
        const oid = document.getElementById('oid-input').value.trim();
        if (!oid) return;
        
        const resultsDiv = document.getElementById('oid-results');
        resultsDiv.innerHTML = '<div class="loading">Loading...</div>';
        
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/oids/get`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ oids: [oid] })
            });
            
            const data = await response.json();
            const value = data.oids && data.oids[0] ? data.oids[0].value : 'No value';
            resultsDiv.innerHTML = this.renderOidResult(oid, { value });
        } catch (error) {
            resultsDiv.innerHTML = '<div class="error">Failed to get OID value</div>';
        }
    }

    async walkOidSubtree() {
        const oid = document.getElementById('oid-input').value.trim();
        if (!oid) return;
        
        const resultsDiv = document.getElementById('oid-results');
        resultsDiv.innerHTML = '<div class="loading">Walking OID subtree...</div>';
        
        try {
            const response = await fetch(`/api/devices/${this.deviceIp}/oids/walk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ base_oid: oid, max_results: 100 })
            });
            
            const data = await response.json();
            resultsDiv.innerHTML = this.renderOidWalkResults(data.oids || []);
        } catch (error) {
            resultsDiv.innerHTML = '<div class="error">Failed to walk OID subtree</div>';
        }
    }

    renderOidResult(oid, data) {
        return `
            <div class="oid-result-item">
                <div class="oid-result-header">
                    <code>${oid}</code>
                    <button class="btn btn-small" onclick="monitor.promptAddWidget('${oid}')">+ Add as Widget</button>
                </div>
                <div class="oid-result-value">${data.value || 'No value'}</div>
            </div>
        `;
    }

    renderOidWalkResults(results) {
        if (results.length === 0) {
            return '<div class="no-data">No OIDs found in this subtree</div>';
        }
        
        return results.map(r => `
            <div class="oid-result-item">
                <div class="oid-result-header">
                    <code>${r.oid}</code>
                    <button class="btn btn-small" onclick="monitor.promptAddWidget('${r.oid}')">+ Add as Widget</button>
                </div>
                <div class="oid-result-value">${r.value}</div>
            </div>
        `).join('');
    }

    promptAddWidget(oid) {
        const name = prompt('Enter widget name:', `OID ${oid}`);
        if (name) {
            this.addWidget(oid, name);
            this.closeOidBrowser();
        }
    }

    // Utilities
    startAutoRefresh() {
        if (this.refreshInterval) clearInterval(this.refreshInterval);
        this.refreshInterval = setInterval(() => {
            this.loadDeviceData();
            this.widgets.forEach(w => this.loadWidgetValue(w));
        }, 5000);
    }

    updateLastUpdate() {
        document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
    }

    formatUptime(seconds) {
        if (!seconds) return '-';
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return `${days}d ${hours}h ${mins}m`;
    }

    getUsageClass(percent) {
        if (percent >= 90) return 'high';
        if (percent >= 70) return 'medium';
        return '';
    }

    showSuccess(message) {
        this.showToast(message, 'success');
    }

    showError(message) {
        this.showToast(message, 'error');
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }, 10);
    }
}

// Initialize
const monitor = new DeviceMonitor();
