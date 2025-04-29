# EKS Karpenter 安装指南


## 创建EKS集群的脚本

apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: eks-wm-fat
  region: eu-central-1
managedNodeGroups:
- name: eks-wm-fat-nodegroups-v1
  amiFamily: AmazonLinux2
  instanceType: c7g.4xlarge
  minSize: 0
  desiredCapacity: 1
  maxSize: 5
  volumeSize: 100
  volumeType: gp3
  privateNetworking: true
  subnets:
  - subnet-043c3cdcfb07c6e4b
  - subnet-03cd416460b0d5ed1
  - subnet-025a3fa9307e8b644
  ssh:
    allow: true
    publicKeyName: eks-pro
  tags:
    k8s.io/node: eksctl-eks-wm-fat-graviton-v1
  propagateASGTags: true
  datavolume:
  preBootstrapCommands:
  - "sudo mkfs.xfs /dev/nvme1n1; sudo mkdir -p /var/lib/containerd ;sudo echo /dev/nvme1n1 /var/lib/containerd xfs defaults,noatime 1 2 >> /etc/fstab"
  - "sudo mount -a"
  additionalVolumes:
  - volumeName: '/dev/xvdb' # required
    volumeSize: 1000
    volumeType: 'gp3'
iam:
  withOIDC: true

addons:
 - name: vpc-cni
 - name: coredns
 - name: kube-proxy






## 1. 安装IAM Role and IAM Policy and Queue

设置环境变量：

```bash
export KARPENTER_NAMESPACE="karpenter"
export KARPENTER_VERSION="1.3.3"
export K8S_VERSION="1.30"
export TEMPOUT="$(mktemp)"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
```

通过CloudFormation部署所需资源：

```bash
curl -fsSL https://raw.githubusercontent.com/aws/karpenter-provider-aws/v"${KARPENTER_VERSION}"/website/content/en/preview/getting-started/getting-started-with-karpenter/cloudformation.yaml  > "${TEMPOUT}" \
&& aws cloudformation deploy \
  --stack-name "Karpenter-${CLUSTER_NAME}" \
  --template-file "${TEMPOUT}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "ClusterName=${CLUSTER_NAME}"
```

## 2. 验证oidc是否存在，没有则创建它

检查OIDC是否存在：

```bash
aws eks describe-cluster --name $CLUSTER_NAME | grep oidc 
```

创建OIDC提供者：

```bash
eksctl utils associate-iam-oidc-provider --cluster ${CLUSTER_NAME} --approve
```

## 3. 添加节点角色aws-auth映射，有节点角色的可以加入集群

```bash
eksctl create iamidentitymapping \
  --username system:node:{{EC2PrivateDNSName}} \
  --cluster  ${CLUSTER_NAME} \
  --arn arn:aws:iam::${AWS_ACCOUNT_ID}:role/KarpenterNodeRole-${CLUSTER_NAME} \
  --group system:bootstrappers \
  --group system:nodes
```

## 4. 创建 iamserviceaccount

```bash
eksctl create iamserviceaccount \
  --cluster $CLUSTER_NAME --name karpenter --namespace karpenter \
  --attach-policy-arn arn:aws:iam::$AWS_ACCOUNT_ID:policy/KarpenterControllerPolicy-$CLUSTER_NAME \
  --approve
```

如果有异常可以考虑，可以考虑删除后重新创建：

```bash
eksctl delete iamserviceaccount \
  --cluster ${CLUSTER_NAME} \
  --name karpenter \
  --namespace karpenter
```

## 5. 之前没有运行过 Amazon EC2 spot 实例，请运行下面命令

```bash
aws iam create-service-linked-role --aws-service-name spot.amazonaws.com
```

## 6. 安装Karpenter

```bash
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter --version "${KARPENTER_VERSION}" \
  --namespace "${KARPENTER_NAMESPACE}" --create-namespace \
  --set "settings.clusterName=${CLUSTER_NAME}" \
  --set "settings.interruptionQueue=${CLUSTER_NAME}" \
  --set serviceAccount.create=false \
  --set serviceAccount.name=karpenter \
  --set nodeSelector."alpha\.eksctl\.io/nodegroup-name"=ng-7dff9970

## 6. 创建Nodepool

kubectl apply -f general-purpose.yaml 



