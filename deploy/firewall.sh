#!/bin/bash
# Open port 8080 for the dashboard on Oracle Linux
# Run as: sudo bash firewall.sh

set -e

echo "Opening port 8080 for dashboard..."

# OS-level firewall
firewall-cmd --permanent --add-port=8080/tcp 2>/dev/null || \
  iptables -I INPUT -p tcp --dport 8080 -j ACCEPT

firewall-cmd --reload 2>/dev/null || true

echo "Done. Remember to also open port 8080 in your Oracle Cloud"
echo "VCN Security List (Ingress Rules) from the web console."
