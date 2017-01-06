/* global Vue */

// ChildNode.remove() polyfill for Internet Explorer
// from: https://github.com/jserz/js_piece/blob/master/DOM/ChildNode/remove()/remove().md
(function (arr) {
  arr.forEach(function (item) {
    item.remove = item.remove || function () {
      this.parentNode.removeChild(this);
    };
  });
})([Element.prototype, CharacterData.prototype, DocumentType.prototype]);


Vue.component("JobDisplay", {
  props: ['job'],
  data: function() {
    return {
      queueLength: this.job.position + 1
    };
  },
  template: `
    <div class="job-display">
      <ErrorDisplay v-if="job.status === 'failed'"
                    :traceback="job.traceback"
                    @dismiss="triggerClose" />
      <div v-else class="box">
        <article class="media">
          <figure v-if="job.thumbnail" class="media-left">
            <p class="mets-preview image">
              <img :src="job.thumbnail">
            </p>
          </figure>
          <div class="media-content">
            <div class="content">
              <h3>{{ job.label || job.metsurl }}</h3>
              <p v-if="job.label">
                <a :href="job.metsurl" class="metsurl">
                  <img src="/static/img/mets.png">
                </a>
              </p>
              <p v-if="job.attribution" class="attribution">
                <img :src="job.attribution.logo">
                <span v-html="job.attribution.owner"></span>
              </p>
            </div>
            <div v-if="showProgressBar" class="columns level">
              <div class="column">
                <span class="tag is-large is-primary">{{ job.status }}</span>
              </div>
              <div class="column is-10">
                <progress class="progress" :value="completionRatio" max="1">
                  {{ job.status }}
                </progress>
              </div>
            </div>
            <p v-if="job.status === 'finished'" class="control has-addons">
              <input @click="onMetsUrlClick" :value="job.result" type="url"
                     class="input metsurl" ref="metsurl" readonly>
              <a :href="viewerUrl" class="button is-info" target="_blank">
                Open in viewer
              </a>
            </div>
          </div>
        </article>
      </div>
    </div>`,
  computed: {
    showProgressBar: function() {
      return (this.job.status === 'queued' || this.job.status === 'started');
    },
    completionRatio: function() {
      if (this.job.status === 'queued') {
        return ((this.queueLength + 1) - (this.job.position + 1)) / (this.queueLength + 1);
      } else if (this.job.status === 'started') {
        return this.job.current_image / this.job.total_images;
      } else {
        return null;
      }
    },
    viewerUrl: function() {
      if (this.job.result) {
        var manifestId = this.job.result.split('/').splice(-2)[0];
        return `/view/${manifestId}`;
      }
    }
  },
  methods: {
    triggerClose: function() {
      this.$emit('dismiss-job', this.job.id);
    },
    onMetsUrlClick: function() {
      this.$refs.metsurl.setSelectionRange(0, this.$refs.metsurl.value.length);
    }
  }
});

Vue.component("NotificationForm", {
  props: ['jobIds'],
  data: function() {
    return {
      viewForm: false,
      recipient: '',
      wasSubmitted: false,
      errorMessage: null,
      invalid: false,
      isLoading: false
    };
  },
  template: `
    <div class="notification-form">
      <p v-if="!viewForm" class="control">
        <label class="checkbox">
          <input v-model="viewForm" type="checkbox"> Notify me via email
        </label>
      </p>
      <p v-else-if="!wasSubmitted" class="control has-addons">
        <input v-model="recipient" :class="{'is-danger': isDisabled}"
               @invalid="invalidate" @click="removeError"
               class="input" type="email" placeholder="Enter your email">
        <button @click="registerForNotifications" :disabled="isDisabled"
                :class="{'is-loading': isLoading}"
                type="submit" class="button">Submit</button>
        <span v-if="isDisabled" class="help is-danger">{{ errorMessage }}</span>\
      </p>
      <div v-else class="notification">
        <button @click="dismiss" class="delete"></button>
        You will be notified at {{ recipient }} once the manifests are finished
      </p>
    </div>`,
  computed: {
    isDisabled: function() {
      return this.invalid || this.errorMessage !== null;
    }
  },
  methods: {
    invalidate: function() {
      this.invalid = true;
    },
    removeError: function() {
      this.errorMessage = null;
      this.invalid = false;
    },
    registerForNotifications: function() {
      var vm = this;
      vm.isLoading = true;
      axios.post('/api/tasks/notify', {recipient: this.recipient,
                                       jobs: this.jobIds})
        .then(function(resp) {
          vm.wasSubmitted = true;
          vm.$emit('subscribe-to-notifications', vm.recipient);
          vm.isLoading = false;
        })
        .catch(function(err) {
          if (err.response) {
            vm.errorMessage = err.response.data.message;
          } else {
            console.error(err);
          }
          vm.isLoading = false;
        });
    },
    dismiss: function() {
      this.$emit('dismiss-notification');
    }
  }
});


Vue.component("ErrorDisplay", {
  props: ['metsUrl', 'traceback'],
  data: function() {
    return {
      showTraceback: false,
      url: this.metsUrl
    };
  },
  template: `
    <article class="message is-danger">
      <div class="message-header">
        <p><strong>Could not import METS</strong></p>
        <button @click="onDismiss" class="delete"></button>
      </div>
      <div class="message-body">
        <div class="container content">
          <p>
            Unfortunately we were unable to generate a IIIF manifest from the METS
            located at
          <p>
          <p class="has-text-centered">
            <a :href="url" target="_blank">{{ url }}</a>.
          </p>
          <p>
            The error was logged in our backend and will be examined. If you wish
            to help with debugging, you can consult the traceback below and open
            an issue on GitHub.
          <p>
          <button class="button is-danger" @click="toggleTraceback">Traceback</button>
          <pre v-if="showTraceback">{{ traceback }}</pre>
        </div>
      </div>
    </article>`,
  methods: {
    onDismiss: function() {
      this.$emit('dismiss');
    },
    toggleTraceback: function() {
      this.showTraceback = !this.showTraceback;
    }
  }
});


Vue.component("MetsForm", {
  props: ['jobIds'],
  data: function() {
    return {
      metsUrl: '',
      errorMessage: null,
      traceback: null,
      showTraceback: false,
      invalid: false,
      showNotificationForm: true,
      subscribedToNotifications: false,
      isLoading: false
    };
  },
  template: `
    <div>
      <NotificationForm v-if="showNotificationForm && hasJobs" :jobIds="jobIds"
                        @subscribe-to-notifications="onSubscribeToNotifications"
                        @dismiss-notification="onDismissNotification"/>
      <form @submit.prevent>
        <div class="columns">
          <p class="column is-11 control">
            <input v-model="metsUrl" type="url" class="input is-large"
                   @click="removeError" name="metsUrl" @invalid="invalidate"
                   placeholder="Put a METS URL in here!"
                   :class="{'is-danger': isDisabled}">
            <span v-if="errorMessage" class="help is-danger">{{ errorMessage }}</span>
          </p>
          <p class="column">
            <button @click="submitUrl" class="button is-primary is-large iiif-btn"
                    type="submit" :disabled="isDisabled"
                    :class="{'is-disabled': isDisabled, 'is-loading': isLoading}">
              <img src="/static/img/iiif_128.png" alt="IIIF it!">
            </button>
          </p>
        </div>
      </form>
      <ErrorDisplay v-if="!errorMessage && traceback" @dismiss="onDismissError"
                    :metsUrl="metsUrl" :traceback="traceback" />
    </div>`,
  computed: {
    isDisabled: function() {
      return this.invalid || this.errorMessage !== null;
    },
    hasJobs: function() {
      return this.jobIds.length > 0;
    }
  },
  methods: {
    invalidate: function() {
      this.invalid = true;
    },
    removeError: function() {
      this.invalid = false;
      this.errorMessage = null;
    },
    onDismissError: function() {
      this.invalid = false;
      this.errorMessage = null;
      this.traceback = null;
    },
    submitUrl: function() {
      var vm = this;
      vm.isLoading = true;
      axios.post('/api/import', {url: this.metsUrl})
        .then(function(resp) {
          vm.errorMessage = null;
          vm.metsUrl = '';
          vm.$emit("new-job", resp.data);
          if (vm.subscribedToNotifications) {
            axios.post('/api/notify', {recipient: vm.subscriptionAddress,
                                       job_ids: [resp.data.id]});
          }
          vm.isLoading = false;
        })
        .catch(function(err) {
          if (err.response && err.response.data.message) {
            vm.errorMessage = err.response.data.message;
          } else if (err.response && err.response.data.traceback) {
            vm.traceback = err.response.data.traceback;
          } else {
            console.error(err);
          }
          vm.isLoading = false;
        });
    },
    onDismissNotification: function() {
      this.showNotificationForm = false;
    },
    onSubscribeToNotifications: function(recipient) {
      this.subscribedToNotifications = true;
      this.subscriptionAddress = recipient;
    }
  }
});


var app = new Vue({
  data: {
    jobIds: [],  // to store the order the jobs were added in
    jobs: {},
    streams: {}
  },
  template: `
    <section class="hero" :class="{'is-fullheight': jobIds.length === 0}">
      <div class="hero-head">
        <nav class="nav">
          <div class="nav-left">
            <a class="nav-item is-brand" href="/">
              demetsiiify
            </a>
          </div>
          <div class="nav-right nav-menu">
            <a class="nav-item" href="/api-docs">API</a>
            <a class="nav-item" href="/about">About</a>
          </div>
        </nav>
      </div>
      <div class="hero-body">
        <div class="container">
          <MetsForm @new-job="onJobCreated" :jobIds="jobIds" />
          <div class="jobs">
            <JobDisplay v-for="jobId in jobIds"
                        :job="jobs[jobId]"
                        @dismiss-job="onJobDismissed" />
          </div>
        </div>
      </div>
      <div class="hero-foot">
        <div class="footer">
          <div class="content has-text-right">
            <p>
              Created by <a href="https://github.com/jbaiter">Johannes Baiter</a>
            </p>
          </div>
        </div>
      </div>
    </section>`,
  methods: {
    onJobCreated: function(job) {
      this.jobIds.push(job.id);
      this.$set(this.jobs, job.id, job);
      var vm = this;
      var eventStream = new EventSource("/api/tasks/" + job.id + "/stream");
      eventStream.addEventListener('message', function(event) {
        vm.$set(vm.jobs, job.id, JSON.parse(event.data));
        if (event.data.status === 'finished' || event.data.status === 'failed') {
          eventStream.close();
        }
      });
      this.$set(this.streams, job.id, eventStream);
    },
    onJobDismissed: function(jobId) {
      this.jobIds.splice(this.jobIds.indexOf(jobId), 1);
      this.$delete(this.jobs, jobId);
    }
  }
});


app.$mount(".app");
