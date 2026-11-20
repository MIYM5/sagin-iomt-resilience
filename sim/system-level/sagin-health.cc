/*
 * sagin-health.cc
 *
 * Paper 1 scenario: clinical QoS resilience of IoMT traffic over a
 * UAV-assisted LEO backhaul under coverage gaps, jamming and DoS.
 *
 * Topology:  [IoMT wearables -> Patient hub] --(A2G radio)--> [UAV relay]
 *            --(UAV-to-LEO radio, bent pipe)--> [Ground gateway] --(backhaul)--> [Hospital]
 *            [Attacker] --> [Gateway]   (DoS flood, scenario S3)
 *            [Jammer near the hub]       (interferes with hub->UAV link, scenario S2)
 *
 * Radio hops are modelled with a system-level link abstraction:
 *   - Hub->UAV path loss: 3GPP TR 38.901 RMa LoS (Table 7.4.1-1), UAV as aerial BS
 *   - UAV->LEO path loss: ns-3 ThreeGppNTNRuralPropagationLossModel (3GPP TR 38.811)
 *   - Rate: attenuated Shannon bound, 3GPP TR 36.942 Annex A.1
 *   - Link adaptation targets 10% BLER per transmission, up to 4 transmissions (HARQ/ARQ)
 * Satellite orbits: ns-3 LeoCircularOrbitMobilityModel (Walker-delta shell).
 * Gateway backhaul, DoS flood and queueing: native ns-3 IP stack, point-to-point, DropTail.
 */

#include "ns3/antenna-module.h"
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/propagation-module.h"

#include <array>
#include <cmath>
#include <deque>
#include <fstream>
#include <functional>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("SaginHealth");

// ---------------------------------------------------------------- configuration
struct SimConfig
{
    // run control
    uint32_t seed = 1;
    uint32_t run = 1;
    std::string outPrefix = "out/run";
    double windowS = 7200;    // measurement window length
    double maxOffsetS = 5400; // random start offset within orbit (varies pass geometry by seed)
    double drainS = 900;      // time after the window for late deliveries

    // policy: P1 max power FIFO, P2 low power FIFO, P3 mid power priority, P4 mid power store&forward
    std::string policy = "P1";

    // scenario: S0 normal, S1 coverage gap (raise mask), S2 jamming, S3 DoS
    std::string scenario = "S0";

    // sites (Tharparkar, Sindh -> gateway near Karachi)
    double hubLat = 24.75, hubLon = 70.20;
    double gwLat = 24.86, gwLon = 67.00;
    double uavAltM = 100.0;
    double hubToUavHorizM = 600.0;

    // constellation (sparse IoT-oriented Walker-delta shell)
    double satAltKm = 550.0, satIncDeg = 53.0;
    uint32_t planes = 6, satsPerPlane = 10;
    double maskDeg = 25.0;   // min elevation at the UAV
    double gwMaskDeg = 25.0; // min elevation at the gateway (bent pipe)
    double visStepS = 1.0;

    // hub->UAV radio
    double hubFcGHz = 2.4, hubBwHz = 1e6, hubNfDb = 7.0;
    double hubTxDbm = 23.0; // set by policy
    double hubAntDbi = 0.0, uavAntDbi = 3.0;
    // device radio power model: 3GPP TR 45.820 Table 7.2.4.5-1 (545 mW TX at +23 dBm with 44 % PA
    // efficiency and 90 mW circuitry; RX active 90 mW; deep sleep 0.015 mW). analyze.py/power.py
    // recompute energy from the logged state times (txTimeS, awakeS), incl. the idle-power sweep.
    double paEff = 0.44, circuitW = 0.09;
    double idleW = 0.09;      // radio awake, not transmitting = RX active (connected mode)
    double sleepW = 0.015e-3; // P4 radio asleep through predicted gaps = deep sleep
    double c3RtoS = 1.0; // C3 end-to-end retransmission timeout (reliable transport)

    // UAV->satellite radio
    double satFcHz = 2.0e9, satBwHz = 1e6;
    // UAV satellite terminal: 3GPP TS 38.101-5 Table 6.2.1-1 power class 1 (31 dBm) in NTN band n256
    // (UL 1980-2010 MHz) with an ARINC 781 intermediate-gain-class antenna (6 dBi): EIRP 37 dBm.
    // Bounds: high-gain 31 dBm + 12 dBi (43 dBm); TR 38.821 handheld 23 dBm + 0 dBi, 360 kHz.
    double uavSatTxDbm = 31.0, uavSatAntDbi = 6.0;
    double satGtDbK = 1.1; // TR 38.821 Set-1 LEO S-band G/T

    // link abstraction (TR 36.942 A.1)
    double alpha = 0.6, sinrMinDb = -10.0, seMax = 4.4;
    double bler = 0.10;
    uint32_t maxTx = 4;
    uint32_t macOverheadB = 40;
    double outageRetryS = 0.02;

    // buffers
    uint32_t hubBufBytes = 4 * 1024 * 1024;
    uint32_t uavBufPkts = 100;

    // traffic
    uint32_t patients = 10;
    double alarmRatePerPatient = 1.0 / 300.0; // C1 Poisson
    uint32_t alarmBytes = 100;
    // C2: single-lead ECG, 200 Hz x 12 bit = 2.4 kbit/s (TR 22.826 sampling), 0.5 s messages
    double ecgPeriodS = 0.5;
    uint32_t ecgBytes = 150;
    double fileIntervalS = 600.0; // C3
    uint32_t fileBytes = 1000000, fragBytes = 1000;

    // S2 jamming
    double jamStartS = 1800, jamDurS = 600, jamDbm = 20.0, jamDistToUavM = 300.0;
    // S3 DoS
    double dosStartS = 3600, dosDurS = 600;
    std::string dosRate = "15Mbps";
    std::string backhaulRate = "10Mbps";
    uint32_t backhaulQueuePkts = 100;
};

static SimConfig g;
static double g_t0 = 0; // measurement window start (absolute sim time)
static Ptr<UniformRandomVariable> g_uni;

// ---------------------------------------------------------------- helpers
static double
DbmToW(double dbm)
{
    return std::pow(10.0, (dbm - 30.0) / 10.0);
}

static double
WToDbm(double w)
{
    return 10.0 * std::log10(w) + 30.0;
}

// attenuated Shannon, 3GPP TR 36.942 Annex A.1; returns bit/s, 0 if below SINRmin
static double
RateBps(double sinrDb, double bwHz)
{
    if (sinrDb < g.sinrMinDb)
    {
        return 0.0;
    }
    double se = g.alpha * std::log2(1.0 + std::pow(10.0, sinrDb / 10.0));
    se = std::min(se, g.seMax);
    return se * bwHz;
}

// 3GPP TR 38.901 RMa LoS PL1 (valid 10 m <= d2D <= dBP); h = avg building height 5 m
static double
RmaLosPathLossDb(double d3D, double fcGHz)
{
    const double h = 5.0;
    return 20.0 * std::log10(40.0 * M_PI * d3D * fcGHz / 3.0) +
           std::min(0.03 * std::pow(h, 1.72), 10.0) * std::log10(d3D) -
           std::min(0.044 * std::pow(h, 1.72), 14.77) + 0.002 * std::log10(h) * d3D;
}

static double
ElevationDeg(const Vector& groundGeo, const Vector& satEcef)
{
    Vector satGeo =
        GeographicPositions::CartesianToGeographicCoordinates(satEcef, GeographicPositions::SPHERE);
    // signature is (pos, refPoint): satellite expressed in the ground site's ENU frame
    Vector topo = GeographicPositions::GeographicToTopocentricCoordinates(
        satGeo,
        groundGeo,
        GeographicPositions::SPHERE);
    Angles a(topo);
    return 90.0 - RadiansToDegrees(a.GetInclination());
}

// ---------------------------------------------------------------- clinical header
class ClinicalHeader : public Header
{
  public:
    uint8_t cls = 0;     // 1 alarm, 2 ecg, 3 file
    uint8_t patient = 0;
    uint32_t seq = 0;    // per-class sequence (for C3: fragment global seq)
    uint64_t genNs = 0;  // generation time, absolute ns
    uint32_t fileId = 0;
    uint16_t frag = 0, nFrag = 0;

    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ClinicalHeader").SetParent<Header>().AddConstructor<ClinicalHeader>();
        return tid;
    }

    TypeId GetInstanceTypeId() const override
    {
        return GetTypeId();
    }

    uint32_t GetSerializedSize() const override
    {
        return 1 + 1 + 4 + 8 + 4 + 2 + 2;
    }

    void Serialize(Buffer::Iterator i) const override
    {
        i.WriteU8(cls);
        i.WriteU8(patient);
        i.WriteHtonU32(seq);
        i.WriteHtonU64(genNs);
        i.WriteHtonU32(fileId);
        i.WriteHtonU16(frag);
        i.WriteHtonU16(nFrag);
    }

    uint32_t Deserialize(Buffer::Iterator i) override
    {
        cls = i.ReadU8();
        patient = i.ReadU8();
        seq = i.ReadNtohU32();
        genNs = i.ReadNtohU64();
        fileId = i.ReadNtohU32();
        frag = i.ReadNtohU16();
        nFrag = i.ReadNtohU16();
        return GetSerializedSize();
    }

    void Print(std::ostream& os) const override
    {
        os << "cls=" << +cls << " seq=" << seq;
    }
};

// ---------------------------------------------------------------- satellite visibility
class Visibility
{
  public:
    NodeContainer sats;
    Vector uavGeo, gwGeo;
    int serving = -1;
    double servingElev = 0;
    std::vector<std::function<void(bool)>> listeners;
    std::ofstream log; // t, up, elev, sat
    double winS = 0, upS = 0; // time in window, and with backhaul up

    bool Up() const
    {
        return serving >= 0;
    }

    void Start()
    {
        Simulator::ScheduleNow(&Visibility::Step, this);
    }

    void Step()
    {
        int best = -1;
        double bestElev = -90;
        for (uint32_t k = 0; k < sats.GetN(); ++k)
        {
            Vector p = sats.Get(k)->GetObject<MobilityModel>()->GetPosition();
            double eU = ElevationDeg(uavGeo, p);
            if (eU < g.maskDeg || eU <= bestElev)
            {
                continue;
            }
            if (ElevationDeg(gwGeo, p) < g.gwMaskDeg)
            {
                continue;
            }
            best = k;
            bestElev = eU;
        }
        bool wasUp = Up();
        serving = best;
        servingElev = bestElev;
        double t = Simulator::Now().GetSeconds();
        if (t >= g_t0 && t <= g_t0 + g.windowS)
        {
            winS += g.visStepS;
            upS += Up() ? g.visStepS : 0.0;
            log << (t - g_t0) << "," << (Up() ? 1 : 0) << "," << (Up() ? bestElev : 0.0) << ","
                << best << "\n";
        }
        if (wasUp != Up())
        {
            for (auto& f : listeners)
            {
                f(Up());
            }
        }
        Simulator::Schedule(Seconds(g.visStepS), &Visibility::Step, this);
    }
};

static Visibility g_vis;

// ---------------------------------------------------------------- hub application
class UavApp;
static size_t UavQueueLen();
static void HubKick();
struct QItem
{
    Ptr<Packet> pkt;
    uint8_t cls;
    double gen;
};

class HubApp : public Application
{
  public:
    Ptr<Socket> sock;
    Address uavAddr;
    Vector hubPos, uavPos, jamPos; // local Cartesian (m), for A2G geometry
    bool priority = false, sfAware = false;
    double energyJ = 0;
    double txTimeS = 0;
    std::ofstream genLog, dropLog, txLog;

  private:
    std::array<std::deque<QItem>, 3> m_q;
    uint64_t m_qBytes = 0;
    bool m_busy = false;
    bool m_retryPending = false;
    uint32_t m_seq[3] = {0, 0, 0};
    uint32_t m_fileId = 0;
    Ptr<ExponentialRandomVariable> m_alarmGap;

    void StartApplication() override
    {
        sock = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        sock->Bind();
        m_alarmGap = CreateObject<ExponentialRandomVariable>();
        m_alarmGap->SetAttribute("Mean", DoubleValue(1.0 / g.alarmRatePerPatient));
        for (uint32_t p = 0; p < g.patients; ++p)
        {
            Simulator::Schedule(Seconds(m_alarmGap->GetValue()), &HubApp::GenAlarm, this, p);
            Simulator::Schedule(Seconds(g_uni->GetValue(0, g.ecgPeriodS)), &HubApp::GenEcg, this, p);
        }
        Simulator::Schedule(Seconds(g_uni->GetValue(0, g.fileIntervalS)), &HubApp::GenFile, this);
        g_vis.listeners.push_back([this](bool) { TrySend(); });
    }

    void StopApplication() override
    {
    }

    bool Active() const
    {
        return Simulator::Now().GetSeconds() <= g_t0 + g.windowS;
    }

    double Rel() const
    {
        return Simulator::Now().GetSeconds() - g_t0;
    }

    void Enqueue(uint8_t cls, uint8_t patient, uint32_t seq, uint32_t fileId, uint16_t frag,
                 uint16_t nFrag, uint32_t bytes)
    {
        ClinicalHeader h;
        h.cls = cls;
        h.patient = patient;
        h.seq = seq;
        h.genNs = Simulator::Now().GetNanoSeconds();
        h.fileId = fileId;
        h.frag = frag;
        h.nFrag = nFrag;
        uint32_t payload = bytes > h.GetSerializedSize() ? bytes - h.GetSerializedSize() : 0;
        Ptr<Packet> p = Create<Packet>(payload);
        p->AddHeader(h);
        genLog << +cls << "," << +patient << "," << seq << "," << fileId << "," << frag << ","
               << nFrag << "," << Rel() << "\n";
        if (m_qBytes + p->GetSize() > g.hubBufBytes)
        {
            dropLog << +cls << "," << seq << "," << Rel() << ",hubbuf\n";
            return;
        }
        m_q[cls - 1].push_back({p, cls, Simulator::Now().GetSeconds()});
        m_qBytes += p->GetSize();
        TrySend();
    }

    void GenAlarm(uint8_t patient)
    {
        if (!Active())
        {
            return;
        }
        Enqueue(1, patient, m_seq[0]++, 0, 0, 1, g.alarmBytes);
        Simulator::Schedule(Seconds(m_alarmGap->GetValue()), &HubApp::GenAlarm, this, patient);
    }

    void GenEcg(uint8_t patient)
    {
        if (!Active())
        {
            return;
        }
        Enqueue(2, patient, m_seq[1]++, 0, 0, 1, g.ecgBytes);
        Simulator::Schedule(Seconds(g.ecgPeriodS), &HubApp::GenEcg, this, patient);
    }

    void GenFile()
    {
        if (!Active())
        {
            return;
        }
        uint16_t n = static_cast<uint16_t>(std::ceil(double(g.fileBytes) / g.fragBytes));
        uint32_t id = m_fileId++;
        for (uint16_t f = 0; f < n; ++f)
        {
            Enqueue(3, 0, m_seq[2]++, id, f, n, g.fragBytes);
        }
        Simulator::Schedule(Seconds(g.fileIntervalS), &HubApp::GenFile, this);
    }

    // which queue to serve: strict priority or FIFO by generation time
    int Pick() const
    {
        int best = -1;
        for (int c = 0; c < 3; ++c)
        {
            if (m_q[c].empty())
            {
                continue;
            }
            if (priority)
            {
                return c;
            }
            if (best < 0 || m_q[c].front().gen < m_q[best].front().gen)
            {
                best = c;
            }
        }
        return best;
    }

  public:
    bool JammerOn() const
    {
        if (g.scenario != "S2")
        {
            return false;
        }
        double t = Rel();
        return t >= g.jamStartS && t < g.jamStartS + g.jamDurS;
    }

    double SinrDb() const
    {
        double d = CalculateDistance(hubPos, uavPos);
        double prx = g.hubTxDbm + g.hubAntDbi + g.uavAntDbi - RmaLosPathLossDb(d, g.hubFcGHz);
        double nW = DbmToW(-174.0 + 10.0 * std::log10(g.hubBwHz) + g.hubNfDb);
        double iW = 0;
        if (JammerOn())
        {
            double dj = CalculateDistance(jamPos, uavPos);
            iW = DbmToW(g.jamDbm + g.uavAntDbi - RmaLosPathLossDb(dj, g.hubFcGHz));
        }
        return prx - WToDbm(nW + iW);
    }

    void TrySend()
    {
        if (m_busy || m_retryPending)
        {
            return;
        }
        if (sfAware && !g_vis.Up())
        {
            return; // store-and-forward: hold until the next pass (listener re-triggers)
        }
        if (UavQueueLen() + 1 >= g.uavBufPkts)
        {
            return; // hop-by-hop flow control: relay has no buffer credit (UAV re-triggers)
        }
        int c = Pick();
        if (c < 0)
        {
            return;
        }
        double rate = RateBps(SinrDb(), g.hubBwHz);
        if (rate <= 0)
        {
            m_retryPending = true; // link outage: re-check shortly, no radio energy spent
            Simulator::Schedule(Seconds(g.outageRetryS), &HubApp::Retry, this);
            return;
        }
        QItem it = m_q[c].front();
        m_q[c].pop_front();
        m_qBytes -= it.pkt->GetSize();
        m_busy = true;
        Attempt(it, 1);
    }

  public:
    // reliable transport for C3: a lost fragment is resent after an RTO
    void Requeue(Ptr<Packet> p)
    {
        Simulator::Schedule(Seconds(g.c3RtoS), &HubApp::DoRequeue, this, p->Copy());
    }

    void DoRequeue(Ptr<Packet> p)
    {
        m_q[2].push_back({p, 3, Simulator::Now().GetSeconds()});
        m_qBytes += p->GetSize();
        TrySend();
    }

    void Retry()
    {
        m_retryPending = false;
        TrySend();
    }

    void Attempt(QItem it, uint32_t txNo)
    {
        double sinr = SinrDb();
        double rate = RateBps(sinr, g.hubBwHz);
        if (rate <= 0)
        {
            // link dropped mid-HARQ: wait and retry this same packet
            Simulator::Schedule(Seconds(g.outageRetryS), &HubApp::Attempt, this, it, txNo);
            return;
        }
        double txTime = (it.pkt->GetSize() + g.macOverheadB) * 8.0 / rate;
        double pElec = DbmToW(g.hubTxDbm) / g.paEff + g.circuitW;
        if (Simulator::Now().GetSeconds() <= g_t0 + g.windowS + 600)
        {
            energyJ += pElec * txTime;
            txTimeS += txTime;
        }
        txLog << Rel() << "," << +it.cls << "," << sinr << "," << txTime << "," << txNo << "\n";
        Simulator::Schedule(Seconds(txTime), &HubApp::TxDone, this, it, txNo);
    }

    void TxDone(QItem it, uint32_t txNo)
    {
        if (g_uni->GetValue() < g.bler)
        {
            if (txNo < g.maxTx)
            {
                Attempt(it, txNo + 1);
                return;
            }
            ClinicalHeader h;
            it.pkt->PeekHeader(h);
            dropLog << +it.cls << "," << h.seq << "," << Rel() << ",hubharq\n";
            if (it.cls == 3)
            {
                Requeue(it.pkt);
            }
        }
        else
        {
            sock->SendTo(it.pkt, 0, uavAddr);
        }
        m_busy = false;
        TrySend();
    }
};

// ---------------------------------------------------------------- UAV relay application
class UavApp : public Application
{
  public:
    Ptr<Socket> rx, tx;
    Address hospAddr;
    Ptr<MobilityModel> uavMob;
    Ptr<ThreeGppPropagationLossModel> ntnLoss;
    std::ofstream dropLog, linkLog;

    bool priority = false; // strict class priority at the relay (P3: end-to-end priority)

  private:
    std::deque<Ptr<Packet>> m_q;
    bool m_busy = false;

    static uint8_t ClsOf(Ptr<Packet> p)
    {
        ClinicalHeader h;
        p->PeekHeader(h);
        return h.cls;
    }

    void StartApplication() override
    {
        rx = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        rx->Bind(InetSocketAddress(Ipv4Address::GetAny(), 5000));
        rx->SetRecvCallback(MakeCallback(&UavApp::Recv, this));
        tx = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        tx->Bind();
        g_vis.listeners.push_back([this](bool) { TrySend(); });
    }

    void StopApplication() override
    {
    }

    double Rel() const
    {
        return Simulator::Now().GetSeconds() - g_t0;
    }

    void Recv(Ptr<Socket> s)
    {
        Ptr<Packet> p;
        Address from;
        while ((p = s->RecvFrom(from)))
        {
            if (m_q.size() >= g.uavBufPkts && priority && ClsOf(p) < 3)
            {
                // push-out: a full relay buffer evicts the newest file fragment (resent by the
                // hub) so that an alarm or ECG sample is not dropped behind bulk data
                for (auto it = m_q.rbegin(); it != m_q.rend(); ++it)
                {
                    if (ClsOf(*it) == 3)
                    {
                        Ptr<Packet> v = *it;
                        m_q.erase(std::next(it).base());
                        ClinicalHeader hv;
                        v->PeekHeader(hv);
                        dropLog << 3 << "," << hv.seq << "," << Rel() << ",uavpushout\n";
                        RequeueAtHub(v);
                        break;
                    }
                }
            }
            if (m_q.size() >= g.uavBufPkts)
            {
                ClinicalHeader h;
                p->PeekHeader(h);
                dropLog << +h.cls << "," << h.seq << "," << Rel() << ",uavbuf\n";
                if (h.cls == 3)
                {
                    RequeueAtHub(p);
                }
                continue;
            }
            m_q.push_back(p);
            TrySend();
        }
    }

    // SNR on the UAV->serving satellite uplink; also returns slant ranges for delay
    double SnrDb(double& dUs, double& dSg)
    {
        Ptr<Node> sat = g_vis.sats.Get(g_vis.serving);
        Ptr<MobilityModel> sm = sat->GetObject<MobilityModel>();
        double prx = ntnLoss->CalcRxPower(g.uavSatTxDbm, uavMob, sm); // dBm, no antenna gains
        double eirpGain = g.uavSatAntDbi;
        // C/N0 = EIRP - L + G/T - k ;  N over bandwidth
        double cn = (prx - 30.0) + eirpGain + g.satGtDbK + 228.6 - 10.0 * std::log10(g.satBwHz);
        Vector gwEcef = GeographicPositions::GeographicToCartesianCoordinates(
            g_vis.gwGeo.x, g_vis.gwGeo.y, g_vis.gwGeo.z, GeographicPositions::SPHERE);
        dUs = CalculateDistance(uavMob->GetPosition(), sm->GetPosition());
        dSg = CalculateDistance(gwEcef, sm->GetPosition());
        return cn;
    }

  public:
    size_t QueueLen() const
    {
        return m_q.size();
    }

    void TrySend()
    {
        if (m_busy || m_q.empty() || !g_vis.Up())
        {
            return;
        }
        auto pick = m_q.begin();
        if (priority)
        {
            // strict priority by class, FIFO within a class
            for (auto it = m_q.begin(); it != m_q.end(); ++it)
            {
                if (ClsOf(*it) < ClsOf(*pick))
                {
                    pick = it;
                }
            }
        }
        Ptr<Packet> p = *pick;
        m_q.erase(pick);
        m_busy = true;
        HubKick(); // buffer credit returned to the hub
        Attempt(p, 1);
    }

    static void RequeueAtHub(Ptr<Packet> p);

    void Attempt(Ptr<Packet> p, uint32_t txNo)
    {
        if (!g_vis.Up())
        {
            // pass ended mid-transfer: put back at the head and wait for the next pass
            m_q.push_front(p);
            m_busy = false;
            return;
        }
        double dUs, dSg;
        double snr = SnrDb(dUs, dSg);
        double rate = RateBps(snr, g.satBwHz);
        if (rate <= 0)
        {
            Simulator::Schedule(Seconds(g.outageRetryS), &UavApp::Attempt, this, p, txNo);
            return;
        }
        double txTime = (p->GetSize() + g.macOverheadB) * 8.0 / rate;
        double prop = (dUs + dSg) / 299792458.0;
        if (txNo == 1 && Rel() >= 0 && Rel() <= g.windowS)
        {
            linkLog << Rel() << "," << snr << "," << rate << "," << prop * 1e3 << "\n";
        }
        Simulator::Schedule(Seconds(txTime), &UavApp::TxDone, this, p, txNo, prop);
    }

    void TxDone(Ptr<Packet> p, uint32_t txNo, double prop)
    {
        if (g_uni->GetValue() < g.bler)
        {
            if (txNo < g.maxTx)
            {
                Attempt(p, txNo + 1);
                return;
            }
            ClinicalHeader h;
            p->PeekHeader(h);
            dropLog << +h.cls << "," << h.seq << "," << Rel() << ",satharq\n";
            if (h.cls == 3)
            {
                RequeueAtHub(p);
            }
        }
        else
        {
            // bent-pipe propagation delay, then into the gateway over the IP stack
            Simulator::Schedule(Seconds(prop), &UavApp::Forward, this, p);
        }
        m_busy = false;
        TrySend();
    }

    void Forward(Ptr<Packet> p)
    {
        tx->SendTo(p, 0, hospAddr);
    }
};

static HubApp* g_hub = nullptr;
static UavApp* g_uav = nullptr;

static size_t
UavQueueLen()
{
    return g_uav ? g_uav->QueueLen() : 0;
}

static void
HubKick()
{
    if (g_hub)
    {
        Simulator::ScheduleNow(&HubApp::TrySend, g_hub);
    }
}

void
UavApp::RequeueAtHub(Ptr<Packet> p)
{
    if (g_hub)
    {
        g_hub->Requeue(p);
    }
}

// backhaul queue drops: log health packets lost at the gateway, resend C3 (reliable transport)
static std::ofstream g_bhDropLog;

static void
BackhaulDrop(Ptr<const Packet> pkt)
{
    Ptr<Packet> p = pkt->Copy();
    PppHeader ppp;
    Ipv4Header ip;
    UdpHeader udp;
    p->RemoveHeader(ppp);
    p->RemoveHeader(ip);
    p->RemoveHeader(udp);
    if (udp.GetDestinationPort() != 6000)
    {
        return; // attacker flood packet
    }
    ClinicalHeader h;
    p->PeekHeader(h);
    g_bhDropLog << +h.cls << "," << h.seq << "," << Simulator::Now().GetSeconds() - g_t0
                << ",backhaul\n";
    if (h.cls == 3)
    {
        UavApp::RequeueAtHub(p);
    }
}

// ---------------------------------------------------------------- hospital sink
class SinkApp : public Application
{
  public:
    std::ofstream rxLog;

  private:
    Ptr<Socket> m_sock;

    void StartApplication() override
    {
        m_sock = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        m_sock->Bind(InetSocketAddress(Ipv4Address::GetAny(), 6000));
        m_sock->SetRecvCallback(MakeCallback(&SinkApp::Recv, this));
    }

    void StopApplication() override
    {
    }

    void Recv(Ptr<Socket> s)
    {
        Ptr<Packet> p;
        while ((p = s->Recv()))
        {
            ClinicalHeader h;
            p->RemoveHeader(h);
            double gen = h.genNs * 1e-9 - g_t0;
            double now = Simulator::Now().GetSeconds() - g_t0;
            rxLog << +h.cls << "," << +h.patient << "," << h.seq << "," << h.fileId << ","
                  << h.frag << "," << h.nFrag << "," << gen << "," << now << "\n";
        }
    }
};

// ---------------------------------------------------------------- main
// ---- link-budget validation mode (--lbCheck=1): reproduce 3GPP TR 38.821 Table 6.1.3.3-1
// S-band LEO uplink cases with the same loss model and C/N formula as UavApp::SnrDb.
// TR 38.821 subtracts a fixed 3 dB shadowing margin; ns-3 draws shadow fading instead, so the
// deterministic check disables shadowing and subtracts the 3 dB margin explicitly.
static double
LbSlantM(double hKm, double elDeg)
{
    const double Re = 6371e3, h = hKm * 1e3, e = elDeg * M_PI / 180.0;
    return std::sqrt(std::pow(Re + h, 2) - std::pow(Re * std::cos(e), 2)) - Re * std::sin(e);
}

static double
LbCnr(double hKm, double elDeg, double txDbm, double antDbi, double gtDbK, double bwHz, bool shadow,
    double extraMarginDb, double fcHz, double lat = 24.75, double lon = 70.2)
{
    Vector ueGeo(lat, lon, 100.0);
    double d = LbSlantM(hKm, elDeg);
    double e = elDeg * M_PI / 180.0;
    // topocentric: due north at the target elevation; refine the range so the geodetic
    // altitude matches the shell height
    Vector satGeo;
    for (int it = 0; it < 30; ++it)
    {
        Vector topo(0.0, d * std::cos(e), d * std::sin(e));
        satGeo = GeographicPositions::TopocentricToGeographicCoordinates(topo, ueGeo,
                                                                         GeographicPositions::WGS84);
        d += (hKm * 1e3 - satGeo.z) * 0.9;
    }
    Ptr<GeocentricEcefMobilityModel> ue = CreateObject<GeocentricEcefMobilityModel>();
    ue->SetGeographicPosition(ueGeo);
    Ptr<GeocentricEcefMobilityModel> sat = CreateObject<GeocentricEcefMobilityModel>();
    sat->SetGeographicPosition(satGeo);
    // the 3GPP loss models key their per-link state on the nodes, so attach both ends to nodes
    CreateObject<Node>()->AggregateObject(ue);
    CreateObject<Node>()->AggregateObject(sat);
    Ptr<ThreeGppNTNRuralPropagationLossModel> ntn =
        CreateObject<ThreeGppNTNRuralPropagationLossModel>();
    ntn->SetChannelConditionModel(CreateObject<AlwaysLosChannelConditionModel>());
    ntn->SetAttribute("Frequency", DoubleValue(fcHz));
    ntn->SetAttribute("ShadowingEnabled", BooleanValue(shadow));
    double prx = ntn->CalcRxPower(txDbm, ue, sat);
    double cn = (prx - 30.0) + antDbi + gtDbK + 228.6 - 10.0 * std::log10(bwHz) - extraMarginDb;
    double el = ue->GetElevationAngle(sat);
    std::cout.precision(3);
    std::cout << std::fixed << "    elev " << el << " deg, slant " << CalculateDistance(
                     ue->GetPosition(), sat->GetPosition()) / 1e3
              << " km, total loss " << txDbm - prx << " dB, CNR " << cn << " dB\n";
    return cn;
}

static int
RunLinkBudgetCheck()
{
    struct Case
    {
        const char* name;
        double hKm, gt, ref;
    } cases[] = {{"SC9/SC10  LEO-600  Set-1", 600, 1.1, 2.8},
                 {"SC14/SC15 LEO-1200 Set-1", 1200, 1.1, -2.6},
                 {"SC24/SC25 LEO-600  Set-2", 600, -4.9, -3.2},
                 {"SC29/SC30 LEO-1200 Set-2", 1200, -4.9, -8.6}};
    std::cout << "TR 38.821 Table 6.1.3.3-1 reproduction (2 GHz UL, handheld 23 dBm/0 dBi, 360 kHz, "
                 "30 deg, 3 dB shadow margin, shadow fading off)\n";
    for (auto& c : cases)
    {
        std::cout << c.name << "  TR 38.821 CNR " << c.ref << " dB\n";
        double v = LbCnr(c.hKm, 30.0, 23.0, 0.0, c.gt, 360e3, false, 3.0, 2e9);
        std::cout << "    difference " << v - c.ref << " dB\n";
    }
    std::cout << "\nThis study's UAV terminal (550 km, Set-1 G/T, 2 GHz, shadow fading off, no margin)\n";
    for (double el : {25.0, 30.0, 45.0, 60.0, 90.0})
    {
        std::cout << " " << el << " deg: main 33 dBm/10 dBi/1 MHz";
        LbCnr(550, el, 33.0, 10.0, 1.1, 1e6, false, 0.0, 2e9);
        std::cout << " " << el << " deg: handheld 23 dBm/0 dBi/360 kHz";
        LbCnr(550, el, 23.0, 0.0, 1.1, 360e3, false, 0.0, 2e9);
    }
    return 0;
}

int
main(int argc, char* argv[])
{
    CommandLine cmd(__FILE__);
    cmd.AddValue("seed", "RNG seed", g.seed);
    cmd.AddValue("run", "RNG run number", g.run);
    cmd.AddValue("out", "Output file prefix", g.outPrefix);
    cmd.AddValue("policy", "P1|P2|P3|P4", g.policy);
    cmd.AddValue("scenario", "S0|S1|S2|S3", g.scenario);
    cmd.AddValue("window", "Measurement window (s)", g.windowS);
    cmd.AddValue("mask", "Min elevation at UAV (deg)", g.maskDeg);
    cmd.AddValue("gwMask", "Min elevation at gateway (deg)", g.gwMaskDeg);
    cmd.AddValue("planes", "Orbital planes", g.planes);
    cmd.AddValue("satsPerPlane", "Satellites per plane", g.satsPerPlane);
    cmd.AddValue("jamDbm", "Jammer power (dBm)", g.jamDbm);
    cmd.AddValue("jamDur", "Jamming window (s)", g.jamDurS);
    cmd.AddValue("dosRate", "DoS flood rate", g.dosRate);
    cmd.AddValue("dosDur", "DoS window (s)", g.dosDurS);
    cmd.AddValue("jamDist", "Jammer distance from the UAV ground point (m)", g.jamDistToUavM);
    cmd.AddValue("gwQueue", "Gateway backhaul queue (packets)", g.backhaulQueuePkts);
    cmd.AddValue("hubTxDbm", "Override hub transmit power (dBm)", g.hubTxDbm);
    cmd.AddValue("uavBuf", "UAV relay buffer (packets)", g.uavBufPkts);
    cmd.AddValue("jamStart", "Jamming start within window (s)", g.jamStartS);
    cmd.AddValue("dosStart", "DoS start within window (s)", g.dosStartS);
    cmd.AddValue("hubFcGHz", "Hub-UAV carrier (GHz)", g.hubFcGHz);
    cmd.AddValue("hubBw", "Hub-UAV bandwidth (Hz)", g.hubBwHz);
    cmd.AddValue("uavSatTx", "UAV satellite-terminal TX power (dBm)", g.uavSatTxDbm);
    cmd.AddValue("uavSatAnt", "UAV satellite-terminal antenna gain (dBi)", g.uavSatAntDbi);
    cmd.AddValue("satBw", "Satellite-hop UL channel bandwidth (Hz)", g.satBwHz);
    cmd.AddValue("satGt", "Satellite G/T (dB/K)", g.satGtDbK);
    bool lbCheck = false;
    cmd.AddValue("lbCheck", "Print the TR 38.821 link-budget check and exit", lbCheck);
    cmd.AddValue("drain", "Drain time after the window (s)", g.drainS);
    int relayPrio = -1;
    cmd.AddValue("relayPrio", "Class priority at the UAV relay: -1 = with hub priority (P3), 0 off, 1 on", relayPrio);
    cmd.Parse(argc, argv);
    if (lbCheck)
    {
        return RunLinkBudgetCheck();
    }

    RngSeedManager::SetSeed(g.seed);
    RngSeedManager::SetRun(g.run);
    g_uni = CreateObject<UniformRandomVariable>();

    // policies
    bool txOverride = false;
    for (int i = 1; i < argc; ++i)
    {
        if (std::string(argv[i]).find("--hubTxDbm") == 0)
        {
            txOverride = true;
        }
    }
    bool priority = false, sfAware = false;
    double polTx = 23.0;
    if (g.policy == "P1")
    {
        polTx = 23.0;
    }
    else if (g.policy == "P2")
    {
        polTx = 0.0;
    }
    else if (g.policy == "P3")
    {
        polTx = 10.0;
        priority = true;
    }
    else if (g.policy == "P4")
    {
        polTx = 10.0;
        sfAware = true;
    }
    else if (g.policy == "P3F")
    {
        polTx = 10.0; // ablation: P3 power, FIFO, always awake (isolates priority and sleep)
    }
    else
    {
        NS_FATAL_ERROR("Unknown policy " << g.policy);
    }
    if (!txOverride)
    {
        g.hubTxDbm = polTx;
    }

    g_t0 = g_uni->GetValue(0, g.maxOffsetS);
    double stopS = g_t0 + g.windowS + g.drainS;

    // ---- nodes
    NodeContainer hub, uav, gw, hosp, atk;
    hub.Create(1);
    uav.Create(1);
    gw.Create(1);
    hosp.Create(1);
    atk.Create(1);

    InternetStackHelper inet;
    inet.Install(NodeContainer(hub, uav, gw, hosp, atk));

    PointToPointHelper fast;
    fast.SetDeviceAttribute("DataRate", StringValue("100Mbps"));
    fast.SetChannelAttribute("Delay", StringValue("1us"));
    auto dHubUav = fast.Install(hub.Get(0), uav.Get(0));
    auto dUavGw = fast.Install(uav.Get(0), gw.Get(0));
    auto dAtkGw = fast.Install(atk.Get(0), gw.Get(0));

    PointToPointHelper backhaul;
    backhaul.SetDeviceAttribute("DataRate", StringValue(g.backhaulRate));
    backhaul.SetChannelAttribute("Delay", StringValue("5ms"));
    backhaul.SetQueue("ns3::DropTailQueue",
                      "MaxSize",
                      QueueSizeValue(QueueSize(std::to_string(g.backhaulQueuePkts) + "p")));
    auto dGwHosp = backhaul.Install(gw.Get(0), hosp.Get(0));

    Ipv4AddressHelper ip;
    ip.SetBase("10.1.1.0", "255.255.255.0");
    auto iHubUav = ip.Assign(dHubUav);
    ip.SetBase("10.1.2.0", "255.255.255.0");
    ip.Assign(dUavGw);
    ip.SetBase("10.1.3.0", "255.255.255.0");
    auto iGwHosp = ip.Assign(dGwHosp);
    ip.SetBase("10.1.4.0", "255.255.255.0");
    ip.Assign(dAtkGw);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    g_bhDropLog.open(g.outPrefix + "_drop_bh.csv");
    g_bhDropLog << "cls,seq,t,where\n";
    DynamicCast<PointToPointNetDevice>(dGwHosp.Get(0))
        ->GetQueue()
        ->TraceConnectWithoutContext("Drop", MakeCallback(&BackhaulDrop));

    // ---- satellites and geometry
    LeoOrbitNodeHelper orbit(Seconds(1));
    g_vis.sats = orbit.CreateNodesAndInstallMobility(
        LeoOrbitalShell(g.satAltKm, g.satIncDeg, g.planes, g.satsPerPlane, 1));
    g_vis.uavGeo = Vector(g.hubLat, g.hubLon, g.uavAltM);
    g_vis.gwGeo = Vector(g.gwLat, g.gwLon, 10.0);
    g_vis.log.open(g.outPrefix + "_vis.csv");
    g_vis.log << "t,up,elev,sat\n";

    Ptr<GeocentricEcefMobilityModel> uavMob = CreateObject<GeocentricEcefMobilityModel>();
    uavMob->SetGeographicPosition(g_vis.uavGeo);
    uav.Get(0)->AggregateObject(uavMob);

    Ptr<ThreeGppNTNRuralPropagationLossModel> ntn = CreateObject<ThreeGppNTNRuralPropagationLossModel>();
    Ptr<ThreeGppNTNRuralChannelConditionModel> cond = CreateObject<ThreeGppNTNRuralChannelConditionModel>();
    cond->SetAttribute("UpdatePeriod", TimeValue(Seconds(1)));
    ntn->SetChannelConditionModel(cond);
    ntn->SetAttribute("Frequency", DoubleValue(g.satFcHz));

    // ---- applications
    Ptr<SinkApp> sink = CreateObject<SinkApp>();
    sink->rxLog.open(g.outPrefix + "_rx.csv");
    sink->rxLog << "cls,patient,seq,fileId,frag,nFrag,gen,rx\n";
    hosp.Get(0)->AddApplication(sink);
    sink->SetStartTime(Seconds(0));

    Ptr<UavApp> ua = CreateObject<UavApp>();
    ua->hospAddr = InetSocketAddress(iGwHosp.GetAddress(1), 6000);
    ua->uavMob = uavMob;
    ua->ntnLoss = ntn;
    ua->dropLog.open(g.outPrefix + "_drop_uav.csv");
    ua->dropLog << "cls,seq,t,where\n";
    ua->linkLog.open(g.outPrefix + "_satlink.csv");
    ua->linkLog << "t,snr,rate,prop_ms\n";
    uav.Get(0)->AddApplication(ua);
    g_uav = PeekPointer(ua);
    ua->SetStartTime(Seconds(0));

    Ptr<HubApp> ha = CreateObject<HubApp>();
    ha->uavAddr = InetSocketAddress(iHubUav.GetAddress(1), 5000);
    ha->priority = priority;
    ua->priority = (relayPrio < 0) ? priority : (relayPrio == 1);
    ha->sfAware = sfAware;
    ha->hubPos = Vector(g.hubToUavHorizM, 0, 1.5);
    ha->uavPos = Vector(0, 0, g.uavAltM);
    ha->jamPos = Vector(-g.jamDistToUavM, 0, 1.5);
    ha->genLog.open(g.outPrefix + "_gen.csv");
    ha->genLog << "cls,patient,seq,fileId,frag,nFrag,gen\n";
    ha->dropLog.open(g.outPrefix + "_drop_hub.csv");
    ha->dropLog << "cls,seq,t,where\n";
    ha->txLog.open(g.outPrefix + "_tx.csv");
    ha->txLog << "t,cls,sinr,txTime,txNo\n";
    hub.Get(0)->AddApplication(ha);
    g_hub = PeekPointer(ha);
    ha->SetStartTime(Seconds(g_t0));

    if (g.scenario == "S3")
    {
        OnOffHelper flood("ns3::UdpSocketFactory", InetSocketAddress(iGwHosp.GetAddress(1), 9999));
        flood.SetConstantRate(DataRate(g.dosRate), 1000);
        auto fa = flood.Install(atk.Get(0));
        fa.Start(Seconds(g_t0 + g.dosStartS));
        fa.Stop(Seconds(g_t0 + g.dosStartS + g.dosDurS));
    }

    g_vis.Start();
    Simulator::Stop(Seconds(stopS));
    Simulator::Run();

    std::ofstream summ(g.outPrefix + "_summary.csv");
    // radio awake time: P1-P3 listen for the whole window; P4 sleeps through predicted gaps
    double awake = sfAware ? g_vis.upS : g_vis.winS;
    double idleJ = g.idleW * std::max(awake - ha->txTimeS, 0.0);
    double sleepJ = g.sleepW * std::max(g_vis.winS - awake, 0.0);
    summ << "policy,scenario,seed,run,t0,hubTxDbm,txEnergyJ,idleEnergyJ,energyJ,mask,planes,"
            "satsPerPlane,jamDbm,dosRate,txTimeS,awakeS,windowS\n";
    summ << g.policy << "," << g.scenario << "," << g.seed << "," << g.run << "," << g_t0 << ","
         << g.hubTxDbm << "," << ha->energyJ << "," << idleJ << ","
         << ha->energyJ + idleJ + sleepJ << "," << g.maskDeg << "," << g.planes << ","
         << g.satsPerPlane << "," << g.jamDbm << "," << g.dosRate << "," << ha->txTimeS << ","
         << awake << "," << g_vis.winS << "\n";
    Simulator::Destroy();
    return 0;
}
